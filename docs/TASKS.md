# Tasks

Work one at a time. Do not skip ahead. Each task ends with `ruff check` and
`pytest` green, plus a commit.

## Phase 1 — Foundation
- [x] T1.1 uv workspace, four packages, ruff + pytest config, Dockerfile per app
- [x] T1.2 docker-compose: Postgres 17 with `vector` and `pg_trgm`, api, web
- [x] T1.3 SQLAlchemy models mirroring the source shape; Alembic initial
      migration. The job's source `invoice_number` field is modelled as
      `job_number`; `job_id` is the only jobs↔invoices join key. Address id is
      nullable. `street_line_2` normalises `null` and `""` to the same value.
- [ ] T1.3a **Layer 0 guard** `test_no_job_invoice_number`: walks the
      `packages/core` AST and fails if `invoice_number` appears on anything
      job-shaped — a column on the jobs table, a Pydantic field on a job schema
      or a tool result carrying one, a key in a job serialiser. The one
      permitted occurrence is the `jobs.jsonl` parsing function, allow-listed
      by qualified name. Asserts the inverse too: the `invoices` model still
      carries `invoice_number`, so the guard cannot be passed by deleting the
      concept. Runs on every commit; see `docs/HARNESS.md` Layer 0.
- [ ] T1.4 Idempotent loaders for jobs, invoices, customers, employees. No
      field from the `.jsonl` is dropped, including ones empty in this export.
      Money stays in cents. The loader logs a WARNING for every value of
      `work_status`, `invoice.status` or `item.type` outside the known sets in
      `switchboard_core.db.source`, with a count, and loads it anyway: the
      schema has no CHECK constraints, and absence of a constraint must not
      become absence of visibility.
- [ ] T1.5 `scripts/verify_load.py` asserting the measured shape in
      `docs/DATA.md`: 1,992 jobs · 6,954 notes · 1,700 invoices · 4,390 line
      items · 732 customers (683 homeowner / 49 business) · 23 employees ·
      1,390 address ids with 4 jobs null · 456 jobs without an invoice · 135
      jobs with more than one (max 4) · 94 without `scheduled_start` · 95
      without a tech · 23 distinct tags

## Phase 2 — Knowledge
- [ ] T2.1 Address canonicalisation: normalised `street` + `street_line_2` +
      `zip` (strip + casefold, `null` == `""`, city excluded), `address_alias`
      table, `pg_trgm` index, `resolve_address` returning `canonical_id`.
      Asserts 1,360 canonical addresses over 1,390 ids, and that the 4 null-id
      jobs resolve.
- [ ] T2.2 `visit_history` derived table keyed on `canonical_id`, returning
      structured rows only — no generated prose. Aggregates the 0-to-4 invoices
      a job may have.
- [ ] T2.3a **Derived install date**: for each canonical address, the
      installation job identified by `description`, taking
      `work_timestamps.completed_at` as the install date, most recent first.
      There is no install date field in the source; level 3 of the warranty
      precedence rule cannot be built without this, and the
      `1 Yr Labor Warranty` tag sits on the install job rather than on the
      service job the caller is phoning about.
- [ ] T2.3b `warranty_status` derived table implementing the six-level
      precedence rule in `docs/DATA.md`, scoped to `canonical_id` plus named
      equipment, always returning the basis and the level. Line item match is
      `ILIKE '%warrant%'` (64 items), with the exact prefix as the parsed case
      and the 3 named exceptions handled. `Warranty Complete` is neutral.
- [ ] T2.4 Callback chain linking, outstanding balances
- [ ] T2.5 Note chunking, embeddings, `tsvector`, RRF hybrid query. Every
      returned date is the job's service date, in a `job_service_date` field.
      Whether the dense leg is kept is decided by measurement in T4.2, not
      assumed — see `docs/ARCHITECTURE.md`.

## Phase 3 — Tools
- [ ] T3.1 Tool contract base: Pydantic in/out, logging decorator with
      `duration_ms`, typed errors. This log is the latency baseline source.
- [ ] T3.2 All read tools
- [ ] T3.3 All write tools with idempotency and audit rows
- [ ] T3.4 `web_search`
- [ ] T3.5 FastAPI exposure of every tool + `scripts/smoke_tools.sh`

## Phase 4 — Harness v1 (before the agent)
- [ ] T4.0 Minimal text tool client: binds the Pydantic tool schemas to a model,
      takes an utterance, returns the tool calls requested. No audio, no
      LiveKit session, no agent class, no handoffs. This is what makes Layers 1
      and 4 runnable before Phase 5 exists.
- [ ] T4.1 40 golden utterances in `evals/golden/tools.yaml`, including the
      **number-provenance case**: the caller asks for the number of a service
      and the assertion is that every number returned traces to a row whose
      `job_id` is the resolved job's — job number equals `job.job_number`,
      invoice number is in that job's invoice set, anything else fails.
      Adversarial fixtures, both real: `job_1da1e743…` (job number 3743, where
      invoice 3743 is Seth Flynn's at another address) and
      `job_28e341b2…` (job number 3611, where invoice 3611 is Charlene
      Whitaker's). See `docs/HARNESS.md`.
- [ ] T4.2 Runner asserting tool sequence and argument shape against T4.0.
      Also settles the dense-vs-lexical question for `search_notes`.
- [ ] T4.3 `evals/baseline.json` measured from the T3.1 `duration_ms` log, per
      tool class, plus a GitHub Actions workflow that fails on regression.
      Layers 0 and 1 and Layer 4 on every commit; Layer 4 reads the log the
      run it belongs to produced.

## Phase 5 — Voice
- [ ] T5.1 Single LiveKit agent, cascade pipeline, tools bound, dialable
- [ ] T5.2 Triage / Service / Dispatch split with handoffs. Triage holds
      `resolve_address`, `resolve_customer`, `identify_caller_role` and nothing
      else; no job, invoice, note or schedule data before identity resolves.
- [ ] T5.3 Booking as a task group with spoken confirmation, against the
      assumed working day in `docs/SCOPE.md`
- [ ] T5.4 Warm transfer with contextual summary. `transfer_to_human` is
      `control`, so it is reachable from the read path.

## Phase 6 — Platform
- [ ] T6.1 FastAPI: calls, tool_calls, jobs, review_queue endpoints
- [ ] T6.2 `LISTEN/NOTIFY` → SSE endpoint
- [ ] T6.3 React: today view, call log, live action feed, job detail. Today
      view excludes stale scheduled jobs and surfaces them in their own bucket.

## Phase 7 — Async agents and tracing
- [ ] T7.1 Post-call trigger on session end
- [ ] T7.2 Extractor agent → structured facts
- [ ] T7.3 Reviewer agent → confidence + proposals into `ai-ready-for-review`
- [ ] T7.4 Langfuse via OpenTelemetry across call and pipeline

## Phase 8 — Harness v2
- [ ] T8.1 `session.run()` conversation evals with LiveKit judges
- [ ] T8.2 Handoff correctness assertions (Layer 3b, pre-deploy)
- [ ] T8.3 Latency assertions per tool class from the eval run's own tool log
- [ ] T8.4 Cases captured from real test calls

## Phase 9 — Ship
- [ ] T9.1 Deploy agent to LiveKit Cloud, api + web to Fly, db to Neon
- [ ] T9.2 Two full dry runs from a real phone
- [ ] T9.3 README with the three deliverables, ARCHITECTURE final pass
- [ ] T9.4 Screen recording of the full demo as a fallback
