#!/usr/bin/env python
"""Layer 1: grade the T4.0 client against `evals/golden/tools.yaml`.

    uv run python evals/runner.py            # all 40
    uv run python evals/runner.py --case ask_address_no_cooling

Two modes, because two different things are being proven.

**Selection (38 cases).** Send the utterance, grade the tool calls that come
back. Nothing is executed - a golden case can assert on a `book_job`
selection without booking anything.

**Provenance (2 cases).** These run the real path and inspect the rows.
Asserting only the sequence would miss the failure that matters: the right
tool returning the wrong number. Those two live in
`evals/test_number_provenance.py` as ordinary tests, because they need no
model, cost nothing, and must break CI on every commit.

What Layer 1 can and cannot grade
---------------------------------
One round trip is one step. Measured against the live model: "when were you
last at 8504 east old mangrove road" returns `resolve_address` and nothing
else, because the `canonical_id` that `get_visit_history` needs does not
exist until the first tool has run.

So a two-element `expects_tools` is graded on its **opening move**. The rest
of the sequence documents intent and becomes gradable at Layer 3, where
there is a conversation to grade. `expects_followup` is recorded and not
graded here for the same reason: this runner sees tool calls, never the
sentence the agent spoke.

What that leaves fully graded is still the load-bearing half: every
`expects_no_tool_call` (the agent asking instead of guessing), every
`forbids_tools` prohibition, and every opening move.
"""

import argparse
import pathlib
import sys
from dataclasses import dataclass, field

import yaml

from switchboard_agent import choose_tools
from switchboard_agent.text_client import NOT_MODEL_SELECTABLE

GOLDEN = pathlib.Path(__file__).parent / "golden" / "tools.yaml"

#: Graded elsewhere, by tests that need no model. See the module docstring.
EXECUTED_ELSEWHERE = "number_provenance"


@dataclass
class Result:
    case_id: str
    passed: bool
    summary: str
    failures: list[str] = field(default_factory=list)


def load_cases() -> list[dict]:
    return yaml.safe_load(GOLDEN.read_text())["cases"]


def grade(case: dict, chosen: list[str]) -> Result:
    """Grade one case against the tool names the model chose."""
    failures: list[str] = []

    # Global: a kind=logic tool is never offered, so it can never be picked.
    # If one shows up, something re-bound it and the whole run is suspect.
    for name in chosen:
        if name in NOT_MODEL_SELECTABLE:
            failures.append(f"picked {name!r}, which is not model-selectable")

    for forbidden in case.get("forbids_tools", []):
        if forbidden in chosen:
            failures.append(f"called {forbidden!r}, which this case forbids")

    if case.get("expects_no_tool_call"):
        if chosen:
            failures.append(f"expected no tool call, got {chosen}")
        summary = "no tool" if not chosen else f"got {chosen}"

    else:
        expected = case.get("expects_tools") or case.get("expects_tool_then_ask")
        opening = expected[0]
        if not chosen:
            failures.append(f"expected to open with {opening!r}, called nothing")
        elif chosen[0] != opening:
            failures.append(
                f"expected to open with {opening!r}, opened with {chosen[0]!r}"
            )
        summary = " → ".join(chosen) if chosen else "(none)"

    return Result(case["id"], not failures, summary, failures)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", help="run one case by id")
    args = parser.parse_args()

    cases = load_cases()
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            sys.exit(f"no case with id {args.case!r}")

    graded, deferred = [], []
    for case in cases:
        if case.get("asserts") == EXECUTED_ELSEWHERE:
            deferred.append(case["id"])
            continue
        chosen = [call.name for call in choose_tools(case["utterance"])]
        graded.append(grade(case, chosen))

    width = max(len(r.case_id) for r in graded)
    for result in graded:
        mark = "PASS" if result.passed else "FAIL"
        print(f"  {mark}  {result.case_id:{width}}  {result.summary}")
        for failure in result.failures:
            print(f"        {failure}")

    passed = sum(1 for r in graded if r.passed)
    print()
    print(f"Layer 1: {passed}/{len(graded)} graded cases passed")
    if deferred:
        print(
            f"{len(deferred)} provenance cases are graded by "
            f"evals/test_number_provenance.py, which runs on every commit: "
            f"{', '.join(deferred)}"
        )
    return 0 if passed == len(graded) else 1


if __name__ == "__main__":
    raise SystemExit(main())
