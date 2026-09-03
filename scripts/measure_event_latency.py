#!/usr/bin/env python
"""T6.2's requirement, measured: a tool call reaches the live stream in
under a second.

    uv run python scripts/measure_event_latency.py

Starts nothing. Point it at a running API:

    uv run uvicorn switchboard_api.main:app --port 8099

What it measures is the whole path a real call takes, not a fragment of it:

    tool invoked
      -> @tool_call logs the seven fields
      -> ToolCallRecorder inserts into ops.tool_calls and commits
      -> the trigger fires pg_notify on its own connection's commit
      -> the SSE endpoint's LISTEN receives it
      -> the frame arrives here

The clock starts before the tool runs, so the tool's own work is inside the
number. That is the honest boundary: the dashboard's question is "how long
after something happened do I see it", not "how fast is the last hop".

Every row it writes carries a call id of its own and is deleted afterwards.
"""

import argparse
import datetime
import json
import statistics
import sys
import threading
import time
import uuid

import httpx
from sqlalchemy import text

from switchboard_core.db.session import create_db_engine, session_factory
from switchboard_core.observability import record_tool_calls
from switchboard_core.tools import VisitHistoryRequest, get_visit_history

#: A real canonical address with real visits, so the tool does real work.
CANONICAL_ID = "cadr_2fa76af76a2a53d2909332ef8c0dba59"

#: docs/ARCHITECTURE.md has no budget for this path; the requirement is the
#: budget. Stated here so a regression has something to fail against.
BUDGET_SECONDS = 1.0


class Stream(threading.Thread):
    """Reads the SSE endpoint, timestamping each frame as it arrives."""

    def __init__(self, base: str) -> None:
        super().__init__(daemon=True)
        self.base = base
        self.arrivals: dict[str, float] = {}
        self.connected = threading.Event()
        self.stop = threading.Event()

    def run(self) -> None:
        with (
            httpx.Client(timeout=None) as client,
            client.stream("GET", f"{self.base}/events") as response,
        ):
            for line in response.iter_lines():
                if self.stop.is_set():
                    return
                if line.startswith(": connected"):
                    self.connected.set()
                    continue
                if not line.startswith("data: "):
                    continue
                arrived = time.perf_counter()
                event = json.loads(line[len("data: ") :])
                call_id = event.get("data", {}).get("call_id")
                if call_id:
                    self.arrivals.setdefault(call_id, arrived)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8099")
    parser.add_argument("--runs", type=int, default=20)
    args = parser.parse_args()

    try:
        httpx.get(f"{args.base}/health", timeout=5)
    except httpx.HTTPError:
        sys.exit(
            f"no API at {args.base}. Start one:\n"
            "  uv run uvicorn switchboard_api.main:app --port 8099"
        )

    stream = Stream(args.base)
    stream.start()
    if not stream.connected.wait(timeout=10):
        sys.exit("the SSE endpoint never said hello")

    record_tool_calls()
    engine = create_db_engine()
    sessions = session_factory(engine)

    call_ids: list[str] = []
    started: dict[str, float] = {}

    for _ in range(args.runs):
        call_id = f"call_latency_{uuid.uuid4().hex[:12]}"
        call_ids.append(call_id)
        with sessions() as session, session.begin():
            started[call_id] = time.perf_counter()
            get_visit_history(
                VisitHistoryRequest(canonical_id=CANONICAL_ID),
                call_id=call_id,
                session=session,
            )
        # Space the runs out so a slow frame is not hidden behind a fast one.
        time.sleep(0.05)

    deadline = time.time() + 10
    while time.time() < deadline and len(stream.arrivals) < len(call_ids):
        time.sleep(0.02)
    stream.stop.set()

    latencies = [
        stream.arrivals[c] - started[c] for c in call_ids if c in stream.arrivals
    ]
    missing = len(call_ids) - len(latencies)

    with sessions() as session, session.begin():
        session.execute(
            text("DELETE FROM ops.tool_calls WHERE call_id = ANY(:ids)"),
            {"ids": call_ids},
        )
    engine.dispose()

    if not latencies:
        sys.exit("no event ever arrived - the stream is not delivering")

    ordered = sorted(latencies)
    p95 = statistics.quantiles(ordered, n=100, method="inclusive")[94]
    print(f"=== tool call to SSE frame, {len(latencies)}/{len(call_ids)} runs ===")
    print(f"  p50 {statistics.median(ordered) * 1000:8.1f} ms")
    print(f"  p95 {p95 * 1000:8.1f} ms")
    print(f"  max {max(ordered) * 1000:8.1f} ms")
    print(f"  budget {BUDGET_SECONDS * 1000:.0f} ms")
    print(f"  measured at {datetime.datetime.now(datetime.UTC).isoformat()}")

    if missing:
        print(f"\n{missing} of {len(call_ids)} never arrived")
        return 1
    if max(ordered) > BUDGET_SECONDS:
        print(f"\nOVER BUDGET: slowest frame took {max(ordered) * 1000:.0f} ms")
        return 1
    print("\nevery frame arrived inside the budget")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
