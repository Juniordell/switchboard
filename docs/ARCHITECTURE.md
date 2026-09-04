# Architecture

## The decision

Facts go to SQL. Prose goes to retrieval. Retrieval only runs after an entity
is resolved.

The corpus is 1.54 MB. The engineering problem is precision, not scale.
"When were you last at 89 Harborlight Shores" is a date sort and a join;
no embedding model performs a date sort. "And what did you do" is prose a tech
typed in an attic, and only retrieval finds that.

## Four data layers

| Layer | Contents | Reached by |
|---|---|---|
| Records | Jobs, customers, addresses, employees, invoices, items — loaded verbatim from `data/` | Never directly |
| Entities | Canonical addresses and customers, `pg_trgm` index, alias table | `resolve_address`, `resolve_customer` — return candidates + confidence, never a silent guess |
| Knowledge | `install_date` materialised at load (the one table here that reduces many candidates to one); `visit_history`, `warranty_status`, callback chains and balances computed at query time — see "Derived knowledge returns rows, not prose" below for why | Typed SQL tools, no model in the path |
| Prose | One chunk per note, `vector` + `tsvector`, scoped to canonical address and job | `search_notes(entity_id, query)` — hybrid, RRF, entity filter required |
| Writes | What the agent booked, moved or noted — `ops.booked_jobs`, `ops.job_reschedules`, `ops.agent_notes`, plus `ops.write_audit` | The three Dispatch write tools. Read paths union it with Records — see "Writes are an overlay" |

Loaders are idempotent. Derived tables always trace back to a source row.

## Writes are an overlay, never a mutation of `source`

`source` mirrors `data/` row for row. `scripts/verify_load.py` asserts its
exact counts — 1,992 jobs, 6,954 notes — on every task, and CLAUDE.md hard
rule 1 freezes the files behind it. An appointment inserted into
`source.jobs` would fail that verification immediately and would be a row
with no origin.

So everything the agent writes lands in `ops` and the read path unions the
two. `get_schedule` reads `source.jobs` left-joined to `ops.job_reschedules`
for the effective slot, unioned with `ops.booked_jobs`. A caller who books
at 14:00 is told about that appointment for the rest of the call.

Three consequences, all deliberate:

- **Staleness is judged on the effective start.** Moving an abandoned
  `scheduled` job into the future revives it, which is what moving it means.
- **An agent booking has no job number.** Job numbers are assigned by the
  field service system; inventing one risks colliding with a real number
  exactly as `invoice_number` already collides with `job_number` in this
  dataset. The agent confirms the appointment without quoting a number until
  the office assigns one.
- **`ops` tables carry no foreign key to `source.jobs`.** A reschedule or a
  note can target a loaded job or one booked minutes ago, and no single
  foreign key points at both tables. The tools check the target exists in
  either place and return a typed error when it does not.

### Idempotency and the audit row

Every write derives a key from the arguments that define *the same write*,
and `ops.write_audit.idempotency_key` is `UNIQUE`. That constraint **is** the
retry guard: checking for the key before inserting is check-then-act, and two
retries of one turn can both find nothing and both book. On conflict the tool
reads back what the first attempt wrote and returns it with `replayed=true`.

Row ids are derived from the key rather than generated, so a retry computes
the same `job_id` and the primary key is a second, independent guard.

Every insert into `ops.write_audit` fires a trigger that `pg_notify`s on
`switchboard_writes`, which T6.2 turns into SSE. The trigger, rather than the
tools, because a write that forgot to announce itself would be invisible with
nothing failing — and because Postgres holds notifications until commit, a
write that rolls back correctly announces nothing.

`job_id` is the only join key between jobs and invoices. The field named
`invoice_number` on a job is the **job number** and is loaded as `job_number`.
See the join trap in `docs/DATA.md`.

## Addresses are canonical, not source ids

The source address id is not a usable key. 1,390 ids, one of them entirely
blank, cover **1,337** real addresses over the 1,389 addressable ones: 51
canonical addresses carry more than one redundant id, and 4 jobs have no
address id at all while three of them carry a complete address.

**Canonical key** = normalised `street` + normalised `street_line_2` + `zip`,
built by `switchboard_core.knowledge.address_normalize` (T2.1). Normalisation
folds case, whitespace, `null`/`""` on the unit, this dataset's
abbreviation-vs-spelled-out variance (toward the abbreviated form — a caller's
utterance is usually truncated, not just abbreviated, and a shorter target
loses less trigram overlap against a query that stops early), and a spoken
house number into digits. City is deliberately excluded: the anonymisation
relocated cities inconsistently, so zip 33162 carries 7 city names and the
same street and zip appears as both "Key Biscayne" and "Miami Beach".

- `address_alias(address_id → canonical_id)` is populated at load, and rebuilt
  from scratch every run rather than upserted in place: `canonical_id` is
  derived from code, not copied from a source id, so it changes whenever the
  normaliser does, and an upsert never removes a primary key an incoming batch
  stopped producing. `address_alias.address_id` is stable and upserts safely.
- `job_canonical_id` (T2.3a) resolves any job to a canonical address directly
  from the job's own flattened `address_street` / `address_street_line_2` /
  `address_zip` columns (T1.3), the same fields used to build
  `canonical_addresses` — no join through `address_alias`, since `canonical_id`
  is a pure function of those three fields. This is what three of the four
  null-address-id jobs need: their street matches an existing canonical group,
  so they resolve exactly like any job with an id. The fourth
  (`job_a8edd70d8b7c`, 69 Plumeria Glen Drive) does not: no `customer_addresses`
  row carries that street at all, so it correctly resolves to nothing.
  Verified to agree with `address_alias` on all 1,992 jobs with zero
  mismatches. Every derived function that needs "which address is this job
  at" — `install_dates`, `get_visit_history`, `evaluate_warranty_status`,
  `find_callback_source` — uses this, not a join on `address_id`.
- `resolve_address` returns `canonical_id`, never `address.id`.
- `get_visit_history` and `evaluate_warranty_status` are both keyed on
  `canonical_id`, as of T2.2 and T2.3b.

Without this, "when were you last here" answers from half the history at 51
addresses, and reports no error while doing it.

## Derived knowledge returns rows, not prose

`visit_history` returns **structured rows** — service date, tech, description,
job number, invoice numbers, outstanding balance — ordered, so "last" is a
fact. It contains no generated summary.

A pre-computed summary would be a model in the data path, which contradicts
the Knowledge layer above, and it freezes at load time: a follow-up the summary
did not anticipate has nowhere to go but back to `search_notes`. The agent
summarises the rows at speaking time, where it has the caller's actual
question. Cheap, current, and auditable against the rows it was given.

Because a job may have up to 4 invoices and 456 jobs have none, invoice numbers
and balances are aggregated per visit, and a visit with no invoice is a normal
row, not a missing one.

**`get_visit_history` is computed at query time, not a materialised table** —
same shape as `resolve_address` and `evaluate_warranty_status`, and for the
same reason: it keeps every job as its own row rather than reducing many
candidates to one, so there is nothing to gain from precomputing it. A
canonical address has 1.4-1.5 jobs on average; the join is trivial live.
`find_callback_source` and `get_customer_balance` (T2.4) are the same shape.
`install_dates` is the one exception, precomputed at load, because it *does*
reduce: many candidate install jobs at an address down to the single most
recent one.

## Retrieval

Two ranked lists, fused with reciprocal rank fusion at `1/(60 + rank)`.
Lexical from `ts_rank_cd` over a `tsvector` column, dense from `pgvector`
cosine distance. No score normalisation, so nothing to get wrong. After the
entity filter the candidate set is typically under 10 rows.

Notes carry no timestamp of their own — a note is `{id, content}`. Every date
`search_notes` returns is the **service date of the job the note belongs to**,
returned in a field named `job_service_date` and spoken as such.

## Agent topology

Three agents on the call, split on a permissions boundary, not for its own sake.

- **Triage** — small fast model. Establishes who is calling, since caller ID is
  redacted. Holds `resolve_address`, `resolve_customer` and
  `identify_caller_role`, and nothing else.
- **Service** — every read tool, no write tool. Handles most calls.
- **Dispatch** — the only agent holding customer-record write tools. Booking
  runs as a task group: collect, confirm out loud, write, with a step-back path.
- **Warm transfer** — carries the reason, the transcript and every promise made
  so far to the human picking up.

### The Triage boundary, stated precisely

Triage's boundary is **not** "no customer data tools" — that was the previous
wording and it contradicted the tool table, since resolving a caller is
inherently a lookup against customer records.

The boundary is: **no job, invoice, note or schedule data is reachable before
identity is resolved.** `resolve_address` and `resolve_customer` return only
address and name candidates with confidence scores. They return no history, no
balance, no note text, no appointment. Everything that describes work done or
work booked lives behind the handoff.

This is what `docs/HARNESS.md` Layer 3b asserts, and it is testable as written:
an unidentified caller must not reach `get_schedule`, `get_visit_history`,
`get_warranty_status` or `search_notes`.

Handoffs return the next agent from inside a tool call; chat context carries
across, so there is no replay cost.

## Async agents

Four are defined. Two are built — see `docs/SCOPE.md` for which and why.

- **Extractor** — structured facts out of the finished transcript: what was
  asked, what was promised, which entities were resolved, what changed.
- **Reviewer** — scores the Extractor's output. Anything below threshold
  becomes a proposal for a human rather than a write. Output lands in the
  review queue tagged `ai-ready-for-review`.
- **Reconciler** — compares what was said on the call against the record after
  the fact: a slot promised versus the slot written, a balance quoted versus
  the invoice, a warranty answer versus the precedence rule's current output.
  Divergence becomes a review-queue item.
- **Dispatcher** — turns approved proposals into scheduled work: assigns a tech
  to jobs that have none, sequences the day, and opens the follow-up leg of a
  callback chain.

All four run after the caller hangs up, where latency stops mattering. None of
them writes to a customer record without a human approving the proposal.

## Latency budget

Budgets are **per tool**, not one number. A single figure hid the fact that a
hybrid retrieval turn and an indexed lookup turn are not the same operation.

| Component | Budget |
|---|---|
| Turn detection | 100 ms |
| STT finalisation | 130 ms |
| LLM first token | 280 ms |
| TTS first byte | 140 ms |
| Network + SIP | 80 ms |
| **Fixed total, no tool** | **730 ms** |

| Tool class | Budget | Filler |
|---|---|---|
| SQL — `resolve_*`, `get_visit_history`, `get_warranty_status`, `get_schedule`, `find_availability` | **40 ms** | no |
| Hybrid retrieval — `search_notes` | **1,300 ms** (measured p95; see below) | **yes, by default** |
| Web — `web_search` | 1,500 ms | yes, by default |

The SQL path lands at 770 ms against a target of 800. It is an indexed lookup
against precomputed tables, which is why 40 ms is realistic.

**`search_notes`'s budget is measured, not the placeholder 250 ms this section
used to guess.** Real numbers, `scripts/prose_measurements.py`, 30 scoped
searches against the live corpus, embedding call and Postgres kept separate
because only one of them is a network call to a service this codebase doesn't
operate:

| Phase | p50 | p95 | max |
|---|---|---|---|
| Embedding call (OpenAI, `text-embedding-3-small`) | 463 ms | **1,298 ms** | 2,029 ms |
| Postgres (the RRF query, entity-filtered) | 2.3 ms | 4.7 ms | 6.4 ms |

The embedding call is the entire budget, by roughly 280x at p95 - Postgres was
never the risk the 250 ms guess implied. `search_notes` **speaks filler at
dispatch time, by default rather than by exception**, so time to first word
stays at the 730 ms fixed cost and the answer follows behind it - a guess that
turned out to be the right call once measured, not a coincidence: nothing
about an entity-filtered 3-10 row Postgres query was ever going to be the slow
part, and the fix for the actual slow part (a synchronous network round trip
to OpenAI) is the same fix that was already in place.

Baselines are **measured, not asserted**. The tool contract logs `duration_ms`
from T3.1 onward; `evals/baseline.json` is populated from those logs, and
Layer 4 asserts p95 per tool class against it. A budget nobody has measured is
a number that gets edited downward until it means nothing.

**Settled, not open**: after the entity filter the candidate set is 3-10 rows,
and the question was whether dense retrieval earns its keep against
`ts_rank_cd` alone at that size. Measured against 20 real, entity-scoped
queries phrased as a caller would speak them (`scripts/prose_measurements.py`;
see `docs/DECISIONS.md`): the hybrid top result and the lexical-only top
result **agreed on only 4 of 20** — in 14 of the 16 disagreements,
`ts_rank_cd` matched **no note at all**, because `plainto_tsquery` requires
every significant term to appear and natural speech rarely shares exact
stemmed vocabulary with a tech's shorthand. The hybrid leg is kept, and now
for a measured reason instead of an assumed one.

## Why cascade rather than speech-to-speech

This agent's job is tool calling, and the harness and the audit trail both run
on text. Cascade gives a readable transcript at every stage. Speech-to-speech
(`gpt-realtime-2.1`) is lower latency and more natural at roughly $0.05/min;
it is the right trade when naturalness is the product, and it is not here.

## Build note

**Both** app images take the repository root as their build context, because
both depend on `packages/core` — the agent binds the tools, the API exposes
them:

```
docker build -f apps/agent/Dockerfile .
docker build -f apps/api/Dockerfile .
```

This note previously named only the agent. The API has the same dependency and
therefore the same constraint.

Each image copies **every** workspace member's `pyproject.toml` into its
dependency layer, including the members it does not build. `uv sync --locked`
compares the workspace on disk against `uv.lock`, and a missing member makes
the lock look stale — the build then fails pointing at the lock rather than at
the absent manifest.

## Where it runs

Three hosts, chosen so nothing about the demo depends on this laptop being
awake. `docs/DEPLOY.md` is the runbook; this is the shape.

| Piece | Host | Note |
|---|---|---|
| Agent | LiveKit Cloud, `us-east` | `lk agent create` builds from source — a prebuilt image is Enterprise-only — so the `Dockerfile` sits at the repository **root**: the build context has to include `packages/core`, and `lk` looks for the file in the directory it is given |
| API + dashboard | Fly, `iad`, one machine | One image, one origin: FastAPI answers `/api`, the built frontend answers everything else. That is why there is no CORS configuration anywhere in this repo |
| Async worker | Fly, same image, second process | Drains `ops.async_jobs`. Without it the queue fills and nothing empties it |
| Database | Neon, `us-east-2` | The agent sits next to it deliberately; from a laptop the same query costs ~150 ms of network |

**Use the direct Neon endpoint, not the pooler.** The pooler is PgBouncer in
transaction mode and it discards `LISTEN` **without an error** — the SSE feed
simply never receives anything, and the dashboard shows a page that looks
merely quiet. Measured both ways: pooled delivers nothing, direct delivers.

**The dispatch rule names the agent, and a wrong name fails silently.** The
call connects, the room is created, nobody joins, and no log anywhere
complains, because neither the agent nor the API was ever involved. The two
sides to compare are `lk sip dispatch list --json | grep -i agentName` and
the `agent_name=` in `apps/agent/src/switchboard_agent/main.py`.

## Observability

Instrumented to the OpenTelemetry GenAI semantic conventions; Langfuse is the
exporter, not the dependency. One trace spans the phone call and the async
agents that ran afterwards.
