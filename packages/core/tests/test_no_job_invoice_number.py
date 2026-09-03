"""Layer 0 guard: the wrong join must be unwritable, not merely forbidden.

``jobs.jsonl`` carries a field called ``invoice_number``. It is the **job**
number, on a different sequence from ``invoices.invoice_number`` and in the same
4-digit range, so joining on it matches 1,687 jobs of which 1,682 belong to
another job and 1,649 to another customer — and reports no error while doing it.
It is the one mistake in this dataset that reads a stranger's record aloud over
the phone. CLAUDE.md hard rule 8.

The rule is enforced three ways, because no single one is sufficient:

1. **Identifier scan.** ``invoice_number`` may appear in application source only
   at the places declared in :data:`ALLOWED_SCOPES`. Anything new fails until
   someone adds it there, which is a diff a reviewer sees.
2. **Schema shape.** Exactly one table in the whole database has a column
   called ``invoice_number``, and it is ``invoices``.
3. **The inverse.** ``invoices`` still has its own number and ``jobs`` still has
   ``job_number``, so the guard cannot be satisfied by deleting the concept.

Tests are not scanned: a test names the field in order to assert its absence.
"""

import ast
from pathlib import Path

import pytest

from switchboard_core.db.base import Base
from switchboard_core.db.source import Invoice, Job

FIELD = "invoice_number"

#: Directories of application source. Tests are excluded on purpose.
SOURCE_ROOTS = (
    "packages/core/src",
    "apps/api/src",
    "apps/agent/src",
    "scripts",
)

#: ``(path relative to the repository root, qualified scope)`` pairs where the
#: identifier is legitimate. Every entry is a deliberate exemption.
ALLOWED_SCOPES = frozenset(
    {
        # The invoice's own number. This is the real one.
        ("packages/core/src/switchboard_core/db/source/invoices.py", "Invoice"),
        # The single read of the source field, where it becomes job_number.
        ("packages/core/src/switchboard_core/load/loaders.py", "load_jobs"),
        # Reading and writing the invoice's own number.
        ("packages/core/src/switchboard_core/load/loaders.py", "load_invoices"),
        # Citing an invoice as warranty evidence (level 2) - the invoice's
        # own number, read from an invoices row joined on job_id, never a
        # job's job_number.
        (
            "packages/core/src/switchboard_core/knowledge/warranty_status.py",
            "_level_2_invoice_items",
        ),
    }
)

#: Alembic revisions are exempt from the scan: a migration says
#: ``op.create_table('invoices', sa.Column('invoice_number', ...))`` as plain
#: strings, and scope alone cannot tell which table a string belongs to. The
#: hole this leaves - a migration adding the column to a job table - is closed
#: by :func:`test_only_the_invoices_table_has_an_invoice_number` together with
#: ``alembic check``, which the task gate runs and which fails if a migration
#: and the models disagree.
EXEMPT_DIRECTORIES = ("packages/core/src/switchboard_core/db/migrations/",)


def repository_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "packages" / "core" / "pyproject.toml").is_file():
            return parent
    raise RuntimeError("could not locate the repository root")


def _docstring_ids(tree: ast.Module) -> set[int]:
    """Constants that are docstrings, which may name the field freely."""
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(id(first.value))
    return found


def find_occurrences(source: str) -> list[tuple[int, str, str]]:
    """Return ``(line, qualified scope, kind)`` for every use of the field.

    Comments never reach the AST and docstrings are skipped, so prose may
    discuss the trap. Everything else counts: names, attributes, keywords,
    arguments and string literals such as ``record["invoice_number"]``.
    """
    tree = ast.parse(source)
    docstrings = _docstring_ids(tree)
    occurrences: list[tuple[int, str, str]] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.scope: list[str] = []

        def _descend(self, node: ast.AST, name: str) -> None:
            self.scope.append(name)
            self.generic_visit(node)
            self.scope.pop()

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._descend(node, node.name)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._descend(node, node.name)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._descend(node, node.name)

        def _record(self, node: ast.AST, kind: str) -> None:
            scope = ".".join(self.scope) or "<module>"
            occurrences.append((node.lineno, scope, kind))  # type: ignore[attr-defined]

        def visit_Name(self, node: ast.Name) -> None:
            if node.id == FIELD:
                self._record(node, "name")
            self.generic_visit(node)

        def visit_Attribute(self, node: ast.Attribute) -> None:
            if node.attr == FIELD:
                self._record(node, "attribute")
            self.generic_visit(node)

        def visit_keyword(self, node: ast.keyword) -> None:
            if node.arg == FIELD:
                self._record(node, "keyword")
            self.generic_visit(node)

        def visit_arg(self, node: ast.arg) -> None:
            if node.arg == FIELD:
                self._record(node, "argument")
            self.generic_visit(node)

        def visit_Constant(self, node: ast.Constant) -> None:
            if node.value == FIELD and id(node) not in docstrings:
                self._record(node, "string")
            self.generic_visit(node)

    Visitor().visit(tree)
    return occurrences


def scan_repository() -> list[tuple[str, str, int, str]]:
    """Every occurrence outside the exempt directories, repo-wide."""
    root = repository_root()
    hits: list[tuple[str, str, int, str]] = []
    for source_root in SOURCE_ROOTS:
        for path in sorted((root / source_root).rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            if relative.startswith(EXEMPT_DIRECTORIES):
                continue
            text = path.read_text(encoding="utf-8")
            if FIELD not in text:
                continue
            for line, scope, kind in find_occurrences(text):
                hits.append((relative, scope, line, kind))
    return hits


def test_invoice_number_appears_only_where_it_is_declared() -> None:
    undeclared = [
        f"{path}:{line} in {scope} ({kind})"
        for path, scope, line, kind in scan_repository()
        if (path, scope) not in ALLOWED_SCOPES
    ]
    assert not undeclared, (
        "invoice_number used outside ALLOWED_SCOPES. On a job it is the JOB "
        "number and joining on it reads another customer's invoice; see "
        "CLAUDE.md hard rule 8. Undeclared uses:\n  " + "\n  ".join(undeclared)
    )


def test_every_declared_exemption_is_still_used() -> None:
    """An exemption nobody needs is an exemption nobody is checking."""
    used = {(path, scope) for path, scope, _, _ in scan_repository()}
    assert ALLOWED_SCOPES - used == set(), (
        f"stale exemptions in ALLOWED_SCOPES: {sorted(ALLOWED_SCOPES - used)}"
    )


def test_only_the_invoices_table_has_an_invoice_number() -> None:
    carrying = {
        table.name for table in Base.metadata.tables.values() if FIELD in table.columns
    }
    assert carrying == {"invoices"}


def test_the_invoices_table_still_has_its_own_number() -> None:
    """The guard must not be satisfiable by deleting the concept."""
    assert FIELD in Invoice.__table__.columns


def test_the_jobs_table_carries_job_number_instead() -> None:
    assert "job_number" in Job.__table__.columns
    assert FIELD not in Job.__table__.columns


@pytest.mark.parametrize(
    ("planted", "kind"),
    [
        ("class Job:\n    invoice_number: str\n", "name"),
        ("def f(job):\n    return job.invoice_number\n", "attribute"),
        ('def f(r):\n    return {"invoice_number": r["invoice_number"]}\n', "string"),
        ("def f(*, invoice_number):\n    return invoice_number\n", "argument"),
        ("def f():\n    g(invoice_number=1)\n", "keyword"),
    ],
)
def test_the_scanner_catches_a_planted_violation(planted: str, kind: str) -> None:
    """The guard is only worth having if it fails when it should."""
    kinds = {found_kind for _, _, found_kind in find_occurrences(planted)}
    assert kind in kinds


def test_the_scanner_ignores_prose() -> None:
    """Docstrings and comments discuss the trap; that is not a violation."""
    prose = (
        '"""The source field invoice_number is the job number."""\n# invoice_number\n'
    )
    assert find_occurrences(prose) == []
