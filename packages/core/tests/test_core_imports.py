"""Guards on the shape of the library, not on its behaviour."""

import subprocess
import sys

import switchboard_core

FRAMEWORK_ROOTS = ("fastapi", "starlette", "uvicorn", "livekit")


def test_core_exposes_a_version() -> None:
    assert switchboard_core.__version__


def test_core_imports_no_framework() -> None:
    """packages/core is a library. Importing it must pull in no framework.

    Runs in a fresh interpreter on purpose: the api tests import FastAPI into
    this one, so checking sys.modules in-process would pass or fail depending
    on test ordering rather than on what switchboard_core actually imports.
    """
    probe = (
        "import switchboard_core, sys\n"
        f"roots = {FRAMEWORK_ROOTS!r}\n"
        "leaked = sorted({m.split('.')[0] for m in sys.modules} & set(roots))\n"
        "print(','.join(leaked))\n"
        "raise SystemExit(1 if leaked else 0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"switchboard_core imported a framework: {result.stdout.strip()}"
    )
