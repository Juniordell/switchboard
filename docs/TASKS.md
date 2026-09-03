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
- [x] T1.3a **Layer 0 guard** `test_no_job_invoice_number`: AST scan of
      `packages/core/src`, `apps/api/src`, `apps/agent/src` and `scripts/`,
      failing if `invoice_number` appears anywhere outside a three-entry
      allow-list — the `Invoice` model column and the two loader reads/writes
      of the real invoice number. Plus a schema-shape check that only
      `invoices` may carry the column, and the inverse: `invoices` still has
      it, `jobs` has `job_number` instead. Migrations are exempt from the scan
      and covered by the schema-shape check plus `alembic check`. Verified
      against a real planted violation, not just synthetic ones. Runs on every
      commit; see `docs/HARNESS.md` Layer 0.
- [x] T1.4 Idempotent loaders for jobs, invoices, customers, employees. No
      field from the `.jsonl` is dropped, including ones empty in this export.
      Money stays in cents. The loader logs a WARNING for every value of
      `work_status`, `invoice.status` or `item.type` outside the known sets in
      `switchboard_core.db.source`, with a count, and loads it anyway: the
      schema has no CHECK constraints, and absence of a constraint must not
      become absence of visibility.
- [x] T1.5 `scripts/verify_load.py` asserting the measured shape in
      `docs/DATA.md`: 1,992 jobs · 6,954 notes · 1,700 invoices · 4,390 line
      items · 732 customers (683 homeowner / 49 business) · 23 employees ·
      1,390 address ids with 4 jobs null · 456 jobs without an invoice · 135
      jobs with more than one (max 4) · 94 without `scheduled_start` · 95
      without a tech · 23 distinct tags

## Phase 2 — Knowledge
- [x] T2.1 Address canonicalisation: normalised `street` + `street_line_2` +
      `zip`, city excluded, in `switchboard_core.knowledge.address_normalize`.
      Normalisation folds case, whitespace, `null` == `""`, abbreviation
      variance toward the abbreviated form, and spoken numbers to digits.
      `knowledge.canonical_addresses` (1,337 rows) + `knowledge.address_alias`
      (address_id → canonical_id, rebuilt from scratch each run, not upserted
      — canonical_id is derived from code, address_id is copied from source).
      `pg_trgm` GIN index on `street_normalized`. `resolve_address` returns up
      to 3 candidates with scores and `canonical_id`, never `address_id`;
      `must_ask` on score < 0.55 or a < 0.05 gap to the runner-up. 3 of the 4
      null-address-id jobs resolve via their raw street; the 4th has no
      matching `customer_addresses` row and stays permanently unreachable via
      `resolve_address` — there is no address record to canonicalise from, so
      no later task closes this, only `job_canonical_id` computed directly
      from the job's own columns reaches it (T2.3a). 54 tests,
      including the hard requirement ("eighty nine harbor light shores" → 89
      Harborlight Shores Blvd W) and a real duplicate-id pair converging on
      one `canonical_id`.
- [x] T2.2 `get_visit_history`, a query-time function keyed on `canonical_id`
      (same shape as `resolve_address` and `evaluate_warranty_status`, and for
      the same reason — no reduction to precompute, ~1.4 jobs per address on
      average), returning structured rows only: job id, `job_number` (never
      `invoice_number` — CLAUDE.md hard rule 8, joined only on `job_id`),
      service date, techs, description, aggregated invoice numbers, balance,
      and the job it was a callback from. Ordered most recent first. 9 tests,
      including a fixture whose `job_number` and `invoice_numbers` are visibly
      different values, proving the join never confuses them.
- [x] T2.3a **Derived install date**: `knowledge.install_dates`, one row per
      canonical address, from jobs whose `description` starts with
      `System Installation`, `New System Installation` or `New Construction`
      (validated by invoice amount — $10k-27k median vs $456 for an ordinary
      repair — and `Registration Needed`/`Complete` tags; `Zone System
      Installation` and `System Relocation` excluded after reading their
      notes, neither is a new system going in), most recent `completed_at`
      per address. Only 62 of 1,337 canonical addresses get a row — an
      install is rare in a six-month export, and level 3 of the warranty
      precedence rule falls through for the rest, expected not broken.
      `job_canonical_id` resolves a job to its canonical address directly
      from the job's own flattened address columns, no `address_alias` join,
      reused by every derived table from here on. Corrected a wrong claim in
      docs/DATA.md along the way: the `1 Yr Labor Warranty` tag sits on
      **service** jobs, not install jobs — zero of the 53 tagged jobs match
      an install description. `knowledge.install_dates.canonical_id` cascades
      on delete from `canonical_addresses`, needed once a second table
      derived by a different build step references the same rebuilt-every-run
      parent.
- [x] T2.3b `evaluate_warranty_status`, the six-level precedence rule from
      `docs/DATA.md`, scoped to `canonical_id` plus named equipment, never a
      job. A typed function reading `source` and `knowledge.install_dates` at
      query time, not a materialised table - same shape as `resolve_address`
      (T2.1), and for the same reason: level 2's line-item match and level
      1's note text are lexical checks over an equipment filter supplied at
      call time, not something a precomputed table can be parameterised by.
      Level 3 delegates to `evaluate_level_3` (built ahead of this task).
      Level 1 is the only level that can return `covered=no`; levels 2 and 3
      never deny, and level 5 (`Warranty Complete`) never independently
      returns a verdict - proven with one of the 24 real tagged jobs, alone
      at its address, landing on level 6 `unknown`, never level 5 `no`.
      Returns `covered` (yes/no/unknown, never a bare bool), `level` (1-6),
      `basis`, `evidence` (one job, invoice, or note), `confidence`. 38 tests
      total across the three new modules, all against real fixtures found by
      scanning the loaded database for a canonical address whose only
      warranty signal is the level under test.
- [x] T2.4 `find_callback_source` (which job a callback-tagged job was about
      — install-callback tags link to `knowledge.install_dates`'s job when
      the address has one, else the most recent completed prior job at the
      same address; measured against all 101 real callback-tagged jobs: 8 via
      install, 53 via prior job, 40 with no findable candidate) and
      `get_customer_balance` (`SUM(job.outstanding_balance)` per
      `customer_id`, verified equal to summing `invoice.due_amount`
      independently — no address canonicalisation needed, `customer_id` is
      already a clean source id). 10 tests.
- [x] T2.5 Note chunking, embeddings, `tsvector`, RRF hybrid query.
      `prose.note_chunks` (`chunk_notes`, free, part of every load — 6,954
      rows, one per note, no split), `content_tsv` a Postgres-generated
      column, `embedding` filled separately (`embed_pending`, paid,
      `python -m switchboard_core.prose` — all 6,954 notes embedded),
      `search_notes`/`rank_candidates` (the RRF query, one SQL statement,
      `entity_id` required and positional — no default, not `Optional`). RRF
      math verified exact against the documented `1/(60+rank)` formula with
      synthetic orthogonal vectors before any real embedding existed.
      **Measured, not assumed** (`scripts/prose_measurements.py`, 30 scoped
      searches, 20 real entity-scoped queries): p95 latency is 1,298 ms for
      the embedding call against 4.7 ms for Postgres — the embedding call is
      the entire budget, by ~280x, confirming the filler-by-default design
      already in `docs/ARCHITECTURE.md` for the right reason. Hybrid RRF and
      `ts_rank_cd` alone agreed on the top result only 4/20 times; 14 of the
      16 disagreements were `ts_rank_cd` matching **no note at all** against
      natural caller phrasing. The dense leg stays, now for a measured
      reason. See `docs/DECISIONS.md`.

## Phase 3 — Tools
- [x] T3.1 Tool contract base: Pydantic in/out, logging decorator with
      `duration_ms`, typed errors. This log is the latency baseline source.
      `tools/call_log.py`: `log_tool_call` logs hard rule 5's seven fields as
      one JSON line per call, failures included, then re-raises — deciding
      what the caller sees is not the logger's job. `duration_ms` is the
      total and is never the only timing available: a result overriding
      `timings()` gets its own breakdown merged into the same record
      (`search_notes` will report `embedding_ms` and `postgres_ms`, since
      T2.5 measured 463 ms of OpenAI against 2-5 ms of Postgres and Layer 4
      must assert those apart). `tools/contract.py`: `ToolResult` (with
      `result_rows()`/`timings()` hooks), `ToolError`, `ToolDomainError`, and
      `tool_call`, which catches **only** `ToolDomainError` — a
      `ValidationError` or `KeyError` propagates, because a polite error
      result hiding a defect is worse than a traceback. `call_id` is
      keyword-only with no default. 22 tests; Phase 2's bare `ValueError`s
      are bridged in T3.2, pinned by a test as a decision, not an accident.
- [x] T3.2 All read tools — the nine read entries in `docs/AGENTS.md`, in
      `switchboard_core/tools/`, each `@tool_call`-wrapped with a Pydantic
      request and a `ToolResult`. `READ_TOOLS` keys them by the name T4.0
      binds. Five wrap Phase 2 (`resolve_address`, `get_visit_history`,
      `get_warranty_status`, `get_customer_balance`, `search_notes`);
      **four did not exist and are new logic**: `resolve_customer`,
      `identify_caller_role`, `get_schedule`, `find_availability`.
      Carries the error bridge T3.1 deferred (`tools/errors.py`).
      `search_notes` now reports `embedding_ms` and `postgres_ms` beside
      the total, via `search_notes_timed`. Three findings worth the
      reviewer's time: trigram similarity measures length, not meaning, so
      "Lighthouse" scoring 1.0 against a customer of that exact name and
      0.48 against "Lighthouse Hospitality" is an **ask**, not a decision
      (two customers are also both named "Starfish Hospitality");
      `find_availability` returns one row per window rather than one per
      free tech, since 15 names for the same 10:00 fills the limit with a
      single option; and a homeowner or property manager cannot even
      construct a `get_schedule` request without a resolved `customer_id`.
      No trigram index for `resolve_customer` and no migration: 732
      customers is a sub-millisecond scan. 76 tests.
- [x] T3.3 All write tools with idempotency and audit rows — `book_job`,
      `move_job`, `add_note`, all Dispatch, in a new **`ops` schema**.
      Writing into `source` was never an option: `verify_load.py` asserts
      1,992 jobs and 6,954 notes on every task, so the first booking would
      have failed the gate. Writes are an overlay and `get_schedule` unions
      them, so a caller is told about the appointment they just made.
      `ops.write_audit.idempotency_key` is `UNIQUE` — the constraint *is*
      the retry guard, since a lookup first is a race two retries both win —
      and row ids are derived from the key, making the primary key a second
      guard. A `NOTIFY` on `switchboard_writes` fires from a **trigger**,
      not the tools, so a write cannot forget to announce itself and a
      rolled-back one announces nothing (T6.2 consumes it). Spoken
      confirmation is a required non-empty field holding the caller's own
      words. **override:** the key is `call_id + slot + address`, not the
      spec's `call_id + slot` — one call booking two buildings into the same
      window is two appointments. An agent booking carries **no job number**;
      the field service system assigns those. Hard rule 4 is a guard test.
      46 tests, including a real committed `NOTIFY` delivery.
      `transfer_to_human` is `control`, not `write` — T5.4.
- [x] T3.4 `web_search` — Tavily over `httpx`, one POST, no SDK and no new
      dependency. **Always returns the source:** `url` is a required field
      and a result without one is dropped rather than passed on. An
      unreachable or unconfigured Tavily is `WebSearchUnavailableError`,
      the same judgement as `RetrievalUnavailableError`. Tests drive a real
      `httpx.MockTransport`, so the outgoing URL, bearer header and body are
      asserted and only the network is stubbed. **Not verified against live
      Tavily: `TAVILY_API_KEY` is empty in `.env`.**
- [x] T3.5 FastAPI exposure of every tool + `scripts/smoke_tools.sh`.
      `POST /tools/{name}` takes the tool's **own** Pydantic request as the
      body, so the schema an agent binds and the schema the API accepts are
      one object; `GET /tools` publishes all 13 schemas — the surface T4.0
      binds. Dispatch is by signature, not a hand-kept table: declaring
      `session` gets one, declaring `as_of` gets the server clock,
      `identify_caller_role` declares neither and gets neither. `call_id` is
      a required header; `X-As-Of` makes a run deterministic. Responses
      carry `ok`, mirroring the call log — a `ToolError` is 200 and a
      malformed body is 422. `smoke_tools.sh` starts its own uvicorn, drives
      all 13 with curl, checks the audit trail, cleans up its own committed
      rows: **15 passed, 0 failed, 1 skipped** (`web_search`, no key). 15
      HTTP tests alongside it.

## Phase 4 — Harness v1 (before the agent)
- [x] T4.0 Minimal text tool client: binds the Pydantic tool schemas to a model,
      takes an utterance, returns the tool calls requested. No audio, no
      LiveKit session, no agent class, no handoffs. This is what makes Layers 1
      and 4 runnable before Phase 5 exists.
      `switchboard_agent.text_client`, in `apps/agent` because that is what
      Phase 5 replaces in place. The seam is
      `choose_tools(utterance) -> list[ToolCall]`; while it holds, the runner
      does not change. **It executes nothing** — selection and execution are
      different jobs, which is what lets a golden case assert on a `book_job`
      call without booking anything. Binds all **13** tools, not 12: dropping
      `web_search` would delete the `search_notes`-first distinction Layer 1
      grades. Schemas come from the tools' own Pydantic models, so there is no
      hand-written copy to drift. 12 tests; the live one is skipped unless
      `HARNESS_LIVE=1`, since each run costs an API call.
- [x] T4.1 40 golden utterances in `evals/golden/tools.yaml`, including the
      **number-provenance case**: the caller asks for the number of a service
      and the assertion is that every number returned traces to a row whose
      `job_id` is the resolved job's — job number equals `job.job_number`,
      invoice number is in that job's invoice set, anything else fails.
      Adversarial fixtures, both real: `job_1da1e743…` (job number 3743, where
      invoice 3743 is Seth Flynn's at another address) and
      `job_28e341b2…` (job number 3611, where invoice 3611 is Charlene
      Whitaker's). See `docs/HARNESS.md`.
      Both fixtures re-verified against the loaded database; the Saltbush
      one is worse than documented — Charlene Whitaker is *also* an Osprey
      Hospitality account, the same company as the other fixture's customer.
      **15 cases are `expects_no_tool_call`**: the turn that asks for the
      missing data rather than guessing a property. `expects_tool_then_ask`
      is a third category — the tool runs, comes back ambiguous, the turn
      ends in a question. One fixture corrected against reality: the address
      pair `docs/DECISIONS.md` cited as ambiguous no longer is (gap 0.061 >
      0.05); the real tie is "old mangrove", 0.565 against 0.565.
- [x] T4.2 Runner asserting tool sequence and argument shape against T4.0.
      `evals/runner.py`, two modes. **Selection (38)** grades the *opening
      move*, because one round trip is one step — measured, not assumed: the
      model returns `resolve_address` and stops, since the `canonical_id`
      `get_visit_history` needs does not exist until the first tool has run.
      Prohibitions and no-tool cases are graded in full; the rest of a
      sequence, and `expects_followup`, become gradable at Layer 3, where
      there is a conversation to grade. **Provenance (2)** lives in
      `evals/test_number_provenance.py` as ordinary tests — no model, no
      cost, runs on every commit, and verified against a *planted* wrong
      join, which makes them fail naming Seth Flynn and Charlene Whitaker as
      the customers whose invoices leaked. **37/38 selection cases pass.**
      The one red case is real and open — see `docs/DECISIONS.md`.
      **Not done in this task:** the dense-vs-lexical re-run. The golden set
      carries 3 `search_notes` cases, not the 20 queries that comparison
      needs, so re-running it here would be a different and weaker
      measurement than T2.5's. It needs its own query set; flagged rather
      than faked.
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
