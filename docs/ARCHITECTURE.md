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
| Knowledge | Derived at load: `visit_history`, `warranty_status`, `install_date`, balances, callback chains | Typed SQL tools, no model in the path |
| Prose | One chunk per note, `vector` + `tsvector`, scoped to canonical address and job | `search_notes(entity_id, query)` — hybrid, RRF, entity filter required |

Loaders are idempotent. Derived tables always trace back to a source row.

`job_id` is the only join key between jobs and invoices. The field named
`invoice_number` on a job is the **job number** and is loaded as `job_number`.
See the join trap in `docs/DATA.md`.

## Addresses are canonical, not source ids

The source address id is not a usable key. 1,390 ids cover 1,360 real
addresses: 30 canonical addresses are split across 31 redundant ids, and 4 jobs
have no address id at all while carrying a complete address.

**Canonical key** = normalised `street` + normalised `street_line_2` + `zip`.
Normalisation is strip + casefold, with `null` and `""` collapsing to the same
empty value. City is deliberately excluded: the anonymisation relocated cities
inconsistently, so zip 33162 carries 7 city names and the same street and zip
appears as both "Key Biscayne" and "Miami Beach".

- `address_alias(address_id → canonical_id)` is populated at load. The source
  id becomes an alias, never a key.
- The 4 null-id jobs still resolve, because the canonical key is derived from
  the address string, which is always present.
- `resolve_address` returns `canonical_id`.
- `visit_history` and `warranty_status` are keyed on `canonical_id`.

Without this, "when were you last here" answers from half the history at 30
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
| Hybrid retrieval — `search_notes` | **250 ms** | **yes, by default** |
| Web — `web_search` | 1,500 ms | yes, by default |

The SQL path lands at 770 ms against a target of 800. It is an indexed lookup
against precomputed tables, which is why 40 ms is realistic.

`search_notes` cannot make that target and should not pretend to. It embeds the
caller's utterance before it touches Postgres — a network round trip that is
serial with everything after it — then runs `ts_rank_cd`, pgvector and the
fusion. Its budget is 250 ms and it **speaks filler at dispatch time, by
default rather than by exception**, so time to first word stays at the 730 ms
fixed cost and the answer follows behind it.

Baselines are **measured, not asserted**. The tool contract logs `duration_ms`
from T3.1 onward; `evals/baseline.json` is populated from those logs, and
Layer 4 asserts p95 per tool class against it. A budget nobody has measured is
a number that gets edited downward until it means nothing.

Open question to settle with Layer 1, not by assumption: after the entity
filter the candidate set is 3–10 rows, and dense retrieval may not be earning
its keep against `ts_rank_cd` plus trigram at that size. Dropping the dense leg
removes the embedding round trip from the hot path entirely. Measure before
building the full T2.5.

## Why cascade rather than speech-to-speech

This agent's job is tool calling, and the harness and the audit trail both run
on text. Cascade gives a readable transcript at every stage. Speech-to-speech
(`gpt-realtime-2.1`) is lower latency and more natural at roughly $0.05/min;
it is the right trade when naturalness is the product, and it is not here.

## Build note

apps/agent depends on packages/core, so its Dockerfile uses the repository root
as build context: `docker build -f apps/agent/Dockerfile .`

## Observability

Instrumented to the OpenTelemetry GenAI semantic conventions; Langfuse is the
exporter, not the dependency. One trace spans the phone call and the async
agents that ran afterwards.
