# Switchboard

A voice front desk and operations platform for **Gulf Breeze Air**, an HVAC
company in Miami, built against six months of their real field-service
records.

Call the number and the agent answers, works out who you are, and answers
from the company's own data — when you were last visited, whether a part is
under warranty, what you owe, when someone can come out — then books, moves
or annotates the work, and hands you to a person when it should. Everything
it did is on a dashboard while the call is still running.

## The three deliverables

| | Where | What proves it |
|---|---|---|
| **Voice agent** on a real US number | `apps/agent` — LiveKit Agents 1.7.1, `AgentServer` + `@server.rtc_session`, deployed to LiveKit Cloud | Eight real inbound calls; the transcripts and every tool call are in `ops.transcript_turns` and `ops.tool_calls` |
| **Operations platform** | `apps/api` (FastAPI, `/api`) + `apps/web` (Vite / React 19 / Tailwind 4 / TanStack Query), one service on Fly | https://switchboard-gulf-breeze.fly.dev — today by tech, call log with per-turn tool calls, job detail with the warranty basis, stale bucket, review queue, live SSE feed |
| **Eval harness with a CI gate** | `evals/`, `.github/workflows/harness.yml` | Layer 0-4; 45 golden cases, 39 graded at Layer 1, one intentional red; the gate exits non-zero on regression past 0.02 |

## What it looks like when it works

From a real call, 2026-09-04 15:50 — an address said badly, resolved,
answered, and booked:

```
caller   "I'm from one hundred entry Bowline, Iowa road"
Triage   resolve_address → 3 candidates → asks which
caller   "The first one."
Service  get_visit_history → "two previous visits at 103 Bowline Isle Rd…"
caller   "I want to schedule another meeting for next week"
Dispatch find_availability → offers times
caller   "September seven 8AM"
Dispatch book_job ✓   audited, with the caller's own words
```

## Run it

`docs/DEPLOY.md` is the runbook — every command in order, from an empty
machine to a phone number that rings. The short version:

```bash
uv sync --all-packages --locked        # --all-packages, or the workspace uninstalls
docker compose up -d db
cd packages/core && uv run alembic upgrade head && cd -
uv run python -m switchboard_core.load
uv run python scripts/verify_load.py   # must print: all 21 checks passed
uv run python -m switchboard_core.prose        # embeddings; costs money
uv run uvicorn switchboard_api.main:app --port 8000
cd apps/web && npm run dev                      # WSL2: binds 0.0.0.0
uv run python -m switchboard_agent.main dev
```

## How it is put together

```
caller ──SIP──▶ LiveKit ──▶ Triage ──▶ Service ──▶ Dispatch
                              │          │           │
                              └──────────┴───────────┴──▶ packages/core tools
                                                              │
                              ops.tool_calls ◀── logged ──────┘
                                    │ NOTIFY
                              SSE ──┴──▶ dashboard      (p95 12.6 ms, measured)

call ends ──▶ ops.async_jobs ──▶ Extractor ──▶ Reviewer ──▶ review queue
```

**Three agents, split on permissions.** Triage establishes identity and
holds nothing that describes work. Service holds every read tool. Dispatch
is the only one with customer-record writes — and that is enforced by
`__init_subclass__` raising `TypeError` at import, not by a prompt:

```python
class Broken(SwitchboardAgent):
    TOOLS = frozenset({"get_schedule", "book_job"})
    # TypeError at import: Broken may not hold write tools: book_job
```

**Four Postgres schemas.** `source` mirrors `data/` row for row and is never
written. `knowledge` and `prose` are derived. `ops` is everything the agent
did — calls, turns, tool calls, writes, the queue. Nothing writes to
`source`, so the provided dataset stays the provided dataset.

**Facts come from SQL, prose from retrieval.** A date, a count, a balance or
a warranty verdict is never answered by a vector search. `search_notes`
requires a resolved entity id; an unscoped semantic search over the corpus
is a bug, not an option.

**Every write is idempotent and audited.** The key is `call_id + slot`, so a
retry cannot book twice, and `ops.write_audit` keeps the caller's own words
that authorised it.

## The parts worth arguing about

The data fights back, and `docs/DECISIONS.md` records every judgement call
with its reason. The four that shaped the most code:

- **`invoice_number` on a job is the job number**, on a different sequence in
  the same 4-digit range. Joining jobs to invoices on it lands on another
  customer's invoice **1,649 times out of 1,992** and reports no error.
  `job_id` is the only join key, a Layer 0 guard fails the build if anything
  joins on the other, and two golden cases assert the numbers a caller hears
  trace to their own job.
- **Warranty is derived and the sources disagree.** Six levels of precedence,
  and every answer carries its basis and level rather than a bare yes or no.
  Level 2 is historical — a part *was* covered on that visit — and that is a
  distinct value in the type, not a caveat in a prompt, because a real call
  turned `covered: yes` into "it's under warranty" about a 2023 invoice.
- **1,337 canonical addresses**, not the 1,367 raw tuples: real suffix and
  directional folding merges more than casefolding does. Spoken house
  numbers concatenate by group — "thirteen sixty three" is 1363, not 76 —
  which took a caller to another property's history before it was fixed.
- **Availability is an assumption, not data.** There is no shift table. The
  assumed working day covers 83% of how this company has actually scheduled,
  and the caveat travels in the result so the agent cannot offer a slot
  without it.

## The harness

Five layers, described in `docs/HARNESS.md`. What matters:

- **45 golden cases.** 14 of them are `expects_no_tool_call` — the correct
  turn asks a question instead of guessing, which is the owner's actual
  complaint answered.
- **Cases captured from real calls.** Every defect a real call exposed became
  a permanent case in `evals/test_captured_calls.py` — the summed spoken
  number, the present-tense warranty, the id accepted in the wrong slot, the
  model with no clock, the kept promise filed as broken.
- **One intentional red.** `role_claim_unverified` is a known gap with an
  owner, not a failure that slipped through: nothing verifies a caller's
  claim about their own role. It is graded, reported, and excluded from the
  gate, and it happened for real on 2026-09-04 when a technician called in.

## Known limitations

- **No authentication.** `docs/SCOPE.md` excluded it, and phone numbers are
  redacted in the dataset so caller ID identifies nobody. An address alone
  reaches an average of 5.4 notes. The tiered design that would close it is
  written down; it was not built the day before delivery.
- **CI is narrower than it looks.** `data/` cannot be committed and there is
  no API key in Actions, so the workflow runs lint and Layer 0 and says
  loudly what it did not run. The suite, Layer 1 and Layer 4 run locally.
- **Two queue tests fail against a shared database.** The deployed worker
  claims jobs the tests queue. Not a regression — the tests need their own
  scope, which is written down and not done.
- **The calendar is nearly empty going forward**, so availability is mostly
  open space rather than a realistic packed day.
