# Architecture

## The decision

Facts go to SQL. Prose goes to retrieval. Retrieval only runs after an entity
is resolved.

The corpus is 1.5 MB. The engineering problem is precision, not scale.
"When were you last at 89 Harborlight Shores" is a date sort and a join;
no embedding model performs a date sort. "And what did you do" is prose a tech
typed in an attic, and only retrieval finds that.

## Four data layers

| Layer | Contents | Reached by |
|---|---|---|
| Records | Jobs, customers, addresses, employees, invoices, items — loaded verbatim from `data/` | Never directly |
| Entities | Normalised addresses and customers, `pg_trgm` index, alias table | `resolve_address`, `resolve_customer` — return candidates + confidence, never a silent guess |
| Knowledge | Derived at load: `visit_history`, `warranty_status`, balances, callback chains | Typed SQL tools, no model in the path |
| Prose | One chunk per note, `vector` + `tsvector`, scoped to job and address | `search_notes(entity_id, query)` — hybrid, RRF, entity filter required |

Loaders are idempotent. Derived tables always trace back to a source row.

## Retrieval

Two ranked lists, fused with reciprocal rank fusion at `1/(60 + rank)`.
Lexical from `ts_rank_cd` over a `tsvector` column, dense from `pgvector`
cosine distance. No score normalisation, so nothing to get wrong. After the
entity filter the candidate set is typically under 10 rows.

## Agent topology

Three agents on the call, split on a permissions boundary, not for its own sake.

- **Triage** — small fast model, read-only, no customer data tools. Establishes
  who is calling, since caller ID is redacted. Hands off.
- **Service** — every read tool, no write tool. Handles most calls.
- **Dispatch** — the only agent holding write tools. Booking runs as a task
  group: collect, confirm out loud, write, with a step-back path.
- **Warm transfer** — carries the reason, the transcript and every promise made
  so far to the human picking up.

Handoffs return the next agent from inside a tool call; chat context carries
across, so there is no replay cost.

Two agents run after the caller hangs up, where latency stops mattering:

- **Extractor** — structured facts out of the finished transcript.
- **Reviewer** — scores its own output, and anything below threshold becomes a
  proposal for a human rather than a write. Output lands in the review queue
  tagged `ai-ready-for-review`.

## Latency budget

Target: under 800 ms from end of caller speech to first synthesised word.

| Component | Budget |
|---|---|
| Turn detection | 100 ms |
| STT finalisation | 130 ms |
| LLM first token | 280 ms |
| Tool round trip | 40 ms |
| TTS first byte | 140 ms |
| Network + SIP | 80 ms |

Tool round trip is the only component fully under our control, which is why
retrieval is entity-scoped and knowledge is precomputed. When a tool will
exceed ~400 ms, the agent speaks filler first.

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