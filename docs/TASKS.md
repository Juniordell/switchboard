# Tasks

Work one at a time. Do not skip ahead. Each task ends with `ruff check` and
`pytest` green, plus a commit.

## Phase 1 — Foundation
- [ ] T1.1 uv workspace, four packages, ruff + pytest config, Dockerfile per app
- [ ] T1.2 docker-compose: Postgres 17 with `vector` and `pg_trgm`, api, web
- [ ] T1.3 SQLAlchemy models mirroring the source shape; Alembic initial migration
- [ ] T1.4 Idempotent loaders for jobs, invoices, customers, employees
- [ ] T1.5 `scripts/verify_load.py` asserting 1,992 jobs and 6,954 notes

## Phase 2 — Knowledge
- [ ] T2.1 Address normalisation + `pg_trgm` index + `resolve_address`
- [ ] T2.2 `visit_history` derived table with per-address summary
- [ ] T2.3 `warranty_status` derived table implementing the precedence rule
- [ ] T2.4 Callback chain linking, outstanding balances
- [ ] T2.5 Note chunking, embeddings, `tsvector`, RRF hybrid query

## Phase 3 — Tools
- [ ] T3.1 Tool contract base: Pydantic in/out, logging decorator, typed errors
- [ ] T3.2 All read tools
- [ ] T3.3 All write tools with idempotency and audit rows
- [ ] T3.4 `web_search`
- [ ] T3.5 FastAPI exposure of every tool + `scripts/smoke_tools.sh`

## Phase 4 — Harness v1 (before the agent)
- [ ] T4.1 40 golden utterances in `evals/golden/tools.yaml`
- [ ] T4.2 Runner asserting tool sequence and argument shape
- [ ] T4.3 `evals/baseline.json` + GitHub Actions workflow that fails on regression

## Phase 5 — Voice
- [ ] T5.1 Single LiveKit agent, cascade pipeline, tools bound, dialable
- [ ] T5.2 Triage / Service / Dispatch split with handoffs
- [ ] T5.3 Booking as a task group with spoken confirmation
- [ ] T5.4 Warm transfer with contextual summary

## Phase 6 — Platform
- [ ] T6.1 FastAPI: calls, tool_calls, jobs, review_queue endpoints
- [ ] T6.2 `LISTEN/NOTIFY` → SSE endpoint
- [ ] T6.3 React: today view, call log, live action feed, job detail

## Phase 7 — Async agents and tracing
- [ ] T7.1 Post-call trigger on session end
- [ ] T7.2 Extractor agent → structured facts
- [ ] T7.3 Reviewer agent → confidence + proposals into `ai-ready-for-review`
- [ ] T7.4 Langfuse via OpenTelemetry across call and pipeline

## Phase 8 — Harness v2
- [ ] T8.1 `session.run()` conversation evals with LiveKit judges
- [ ] T8.2 Handoff correctness assertions
- [ ] T8.3 Latency assertions from the tool log
- [ ] T8.4 Cases captured from real test calls

## Phase 9 — Ship
- [ ] T9.1 Deploy agent to LiveKit Cloud, api + web to Fly, db to Neon
- [ ] T9.2 Two full dry runs from a real phone
- [ ] T9.3 README with the three deliverables, ARCHITECTURE final pass
- [ ] T9.4 Screen recording of the full demo as a fallback