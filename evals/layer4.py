#!/usr/bin/env python
"""Layer 4: p95 per tool class, against the budgets in ARCHITECTURE.md.

    uv run pytest                              # produces the log
    uv run python evals/layer4.py              # asserts against the baseline
    uv run python evals/layer4.py --write-baseline

It reads `evals/last_run_tool_calls.jsonl`, which the pytest session writes
from the `switchboard_core.tools` logger. `docs/HARNESS.md`: Layer 4
measures **the tool call log produced by the eval run that is executing**.
Asserting against a borrowed corpus produces a number that means nothing, so
this refuses to run against a log it did not just see written.

The honest part
---------------
Two of the four classes cannot be measured end to end by a test suite, and
the numbers here say so rather than implying otherwise.

- **hybrid** (`search_notes`) is asserted on `postgres_ms`, not on the
  total. The suite stubs the OpenAI call, so its `duration_ms` omits the leg
  that T2.5 measured at 463 ms p50 / 1,298 ms p95. This is exactly why T3.1
  made a result able to report partial timings: the database leg is real
  here even when the network leg is not.
- **web** (`web_search`) never reaches Tavily in the suite - there is no key
  - so its rows are the typed-error path and are reported, not budgeted.

`SQL` and `write` are measured in full: they touch nothing but Postgres.

The regression band has an absolute floor as well as a relative one, and
the floor was measured rather than picked: run to run on an unchanged
tree, these p95s move by up to 0.56 ms and up to 12%. Without the floor a
`web_search` error path at 0.17 ms growing to 0.20 ms is a 16%
"regression" - and a gate that cries wolf on jitter is one people learn
to ignore, which is worse than not having it.
"""

import argparse
import collections
import datetime
import json
import pathlib
import statistics
import sys

from switchboard_core.tools import READ_TOOLS, WRITE_TOOLS

HERE = pathlib.Path(__file__).parent
LOG = HERE / "last_run_tool_calls.jsonl"
BASELINE = HERE / "baseline.json"

TOOLS = {**READ_TOOLS, **WRITE_TOOLS}

#: `docs/ARCHITECTURE.md`'s per-class budgets. `logic` reads nothing and
#: `write` is an insert; neither has a published budget, so they are
#: measured and reported without a ceiling to fail against.
BUDGETS_MS = {"SQL": 40, "hybrid": 1300, "web": 1500}

#: The field each class is judged on. `search_notes` is judged on its
#: Postgres leg because the suite does not pay for the network one.
MEASURED_FIELD = {"hybrid": "postgres_ms"}

#: Regression band, matching the runner and `docs/HARNESS.md`.
TOLERANCE = 0.02

#: A growth must clear this many milliseconds as well as the relative
#: band. **Measured, not chosen**: five consecutive suite runs against an
#: unchanged tree moved SQL's p95 across 9.09-9.65 ms (0.56 ms spread),
#: write across 3.45-3.80, and web across 0.17-0.19 - which is 12%
#: relative on a number too small for a percentage to mean anything. One
#: millisecond sits above every observed jitter and far below a real
#: regression: SQL slowing 25% is +2.3 ms and still fails.
ABSOLUTE_FLOOR_MS = 1.0


def load_calls() -> list[dict]:
    if not LOG.exists():
        sys.exit(
            f"no {LOG.name}: run `uv run pytest` first. Layer 4 asserts against "
            "the log the run it belongs to produced, never a borrowed one."
        )
    return [json.loads(line) for line in LOG.read_text().splitlines() if line.strip()]


def measure(calls: list[dict]) -> dict[str, dict]:
    by_kind: dict[str, list[float]] = collections.defaultdict(list)
    counts: collections.Counter = collections.Counter()

    for call in calls:
        tool = TOOLS.get(call["tool"])
        if tool is None:
            continue
        kind = tool.tool_kind
        counts[kind] += 1
        field = MEASURED_FIELD.get(kind, "duration_ms")
        if field in call:
            by_kind[kind].append(call[field])

    measured = {}
    for kind, samples in sorted(by_kind.items()):
        ordered = sorted(samples)
        # method="inclusive": the default extrapolates past the observed
        # range on small samples, which produced a p95 above the max.
        # A measured percentile must never exceed what was measured.
        p95 = (
            statistics.quantiles(ordered, n=100, method="inclusive")[94]
            if len(ordered) > 1
            else ordered[0]
        )
        measured[kind] = {
            "calls": counts[kind],
            "measured_on": MEASURED_FIELD.get(kind, "duration_ms"),
            "p50_ms": round(statistics.median(ordered), 3),
            "p95_ms": round(p95, 3),
            "max_ms": round(max(ordered), 3),
            "budget_ms": BUDGETS_MS.get(kind),
        }
    return measured


def report(measured: dict[str, dict]) -> None:
    print(f"{'kind':<8}{'calls':>7}{'p50':>10}{'p95':>10}{'max':>10}  budget  on")
    for kind, row in measured.items():
        budget = row["budget_ms"]
        over = budget is not None and row["p95_ms"] > budget
        flag = "  OVER" if over else ""
        print(
            f"{kind:<8}{row['calls']:>7}{row['p50_ms']:>10.2f}"
            f"{row['p95_ms']:>10.2f}{row['max_ms']:>10.2f}"
            f"{str(budget) if budget else '   -':>8}  {row['measured_on']}{flag}"
        )
    print()
    print(
        "hybrid is measured on postgres_ms: the suite stubs the embedding call, "
        "whose real p95 T2.5 put at 1,298 ms."
    )
    print("web never reaches Tavily here - no key - so those rows are not budgeted.")


def gate(measured: dict[str, dict]) -> int:
    failures = []

    for kind, row in measured.items():
        budget = row["budget_ms"]
        if budget is not None and row["p95_ms"] > budget:
            failures.append(
                f"{kind}: p95 {row['p95_ms']:.2f} ms over the {budget} ms budget"
            )

    if BASELINE.exists():
        baseline = json.loads(BASELINE.read_text()).get("layer4", {})
        for kind, row in measured.items():
            before = baseline.get(kind, {}).get("p95_ms")
            if before is None or before <= 0:
                continue
            growth = (row["p95_ms"] - before) / before
            grew = row["p95_ms"] - before
            if growth > TOLERANCE and grew > ABSOLUTE_FLOOR_MS:
                failures.append(
                    f"{kind}: p95 {row['p95_ms']:.2f} ms is {growth:.1%} "
                    f"(+{grew:.2f} ms) above the baseline {before:.2f} ms, "
                    f"past the {TOLERANCE:.0%} band"
                )

    if failures:
        print()
        for failure in failures:
            print(f"REGRESSION: {failure}")
        return 1

    print("\nno regression against the baseline")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args()

    measured = measure(load_calls())
    if not measured:
        sys.exit("the log contains no tool calls this build knows about")
    report(measured)

    if args.write_baseline:
        existing = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
        existing["layer4"] = measured
        existing["measured_at"] = datetime.datetime.now(datetime.UTC).isoformat()
        BASELINE.write_text(json.dumps(existing, indent=2) + "\n")
        print(f"\nwrote {BASELINE.name}")
        return 0

    return gate(measured)


if __name__ == "__main__":
    raise SystemExit(main())
