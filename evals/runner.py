#!/usr/bin/env python
"""Layer 1: grade the T4.0 client against `evals/golden/tools.yaml`.

    uv run python evals/runner.py                 # grade against the baseline
    uv run python evals/runner.py --case <id>     # one case
    uv run python evals/runner.py --write-baseline

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

Intentional reds
----------------
A case marked `intentional_red` is a known gap with an owner, not a failure
that slipped through. It is graded and reported, and it does not fail the
gate - the gate exists to catch a **green turning red**. A red that starts
passing is reported loudly instead, because that means the gap may have
closed and the marker should come off.
"""

import argparse
import datetime
import json
import pathlib
import sys
from dataclasses import dataclass, field

import yaml

from switchboard_agent import choose_tools
from switchboard_agent.text_client import NOT_MODEL_SELECTABLE

HERE = pathlib.Path(__file__).parent
GOLDEN = HERE / "golden" / "tools.yaml"
BASELINE = HERE / "baseline.json"

#: Graded elsewhere, by tests that need no model. See the module docstring.
EXECUTED_ELSEWHERE = "number_provenance"

#: `docs/HARNESS.md`: judged metrics are stochastic and get a band. Layer 1
#: has no judge and runs at temperature 0, so this is slack it should never
#: need - it is here so the gate rule is the same one the doc states.
TOLERANCE = 0.02


@dataclass
class Result:
    case_id: str
    passed: bool
    summary: str
    intentional_red: str | None = None
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

    return Result(
        case_id=case["id"],
        passed=not failures,
        summary=summary,
        intentional_red=case.get("intentional_red"),
        failures=failures,
    )


def run(cases: list[dict]) -> tuple[list[Result], list[str]]:
    results, deferred = [], []
    for case in cases:
        if case.get("asserts") == EXECUTED_ELSEWHERE:
            deferred.append(case["id"])
            continue
        chosen = [call.name for call in choose_tools(case["utterance"])]
        results.append(grade(case, chosen))
    return results, deferred


def report(results: list[Result], deferred: list[str]) -> dict:
    width = max(len(r.case_id) for r in results)
    for result in results:
        if result.intentional_red and not result.passed:
            mark = "RED*"
        elif result.passed:
            mark = "PASS"
        else:
            mark = "FAIL"
        print(f"  {mark}  {result.case_id:{width}}  {result.summary}")
        for failure in result.failures:
            print(f"        {failure}")

    graded = [r for r in results if not r.intentional_red]
    reds = [r for r in results if r.intentional_red]
    passed = sum(1 for r in graded if r.passed)
    rate = passed / len(graded) if graded else 1.0

    print()
    print(f"Layer 1: {passed}/{len(graded)} graded cases passed  (rate {rate:.3f})")
    for red in reds:
        state = "still red" if not red.passed else "NOW PASSING"
        print(
            f"  RED*  {red.case_id}: intentional, owned by {red.intentional_red} "
            f"- {state}"
        )
    if deferred:
        print(
            f"  {len(deferred)} provenance cases graded by "
            f"evals/test_number_provenance.py on every commit: "
            f"{', '.join(deferred)}"
        )
    return {
        "pass_rate": round(rate, 4),
        "passed": passed,
        "graded": len(graded),
        "failed": sorted(r.case_id for r in graded if not r.passed),
        "intentional_red": {r.case_id: r.intentional_red for r in reds},
        "provenance_cases": sorted(deferred),
    }


def gate(summary: dict) -> int:
    """Non-zero on a regression past the tolerance, or on any newly red case."""
    if not BASELINE.exists():
        print("\nno baseline; run with --write-baseline to record one")
        return 0

    baseline = json.loads(BASELINE.read_text())["layer1"]
    drop = baseline["pass_rate"] - summary["pass_rate"]

    if drop > TOLERANCE:
        print(
            f"\nREGRESSION: pass rate {summary['pass_rate']:.3f} is "
            f"{drop:.3f} below the baseline {baseline['pass_rate']:.3f}, "
            f"past the {TOLERANCE} tolerance"
        )
        return 1

    newly_red = set(summary["failed"]) - set(baseline["failed"])
    if newly_red:
        print(f"\nREGRESSION: newly failing cases: {', '.join(sorted(newly_red))}")
        return 1

    for case_id in summary["intentional_red"]:
        if case_id not in baseline["intentional_red"]:
            print(f"\nnew intentional red not in the baseline: {case_id}")
            return 1

    print("\nno regression against the baseline")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", help="run one case by id")
    parser.add_argument(
        "--write-baseline", action="store_true", help="record this run as the baseline"
    )
    args = parser.parse_args()

    cases = load_cases()
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            sys.exit(f"no case with id {args.case!r}")

    results, deferred = run(cases)
    summary = report(results, deferred)

    if args.write_baseline:
        existing = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
        existing["layer1"] = summary
        existing["measured_at"] = datetime.datetime.now(datetime.UTC).isoformat()
        BASELINE.write_text(json.dumps(existing, indent=2) + "\n")
        print(f"\nwrote {BASELINE.relative_to(BASELINE.parents[1])}")
        return 0

    return gate(summary)


if __name__ == "__main__":
    raise SystemExit(main())
