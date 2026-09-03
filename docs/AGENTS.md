# Agents and tools

All tools live in `packages/core/src/switchboard_core/tools/`. They are
ordinary typed Python functions with Pydantic argument models. The voice agent
binds them; the FastAPI app exposes them; the async agents import them. One
implementation.

## Tool contract

Built in T3.1: `tools/call_log.py` (the logging decorator) and
`tools/contract.py` (`ToolResult`, `ToolError`, `ToolDomainError`,
`tool_call`).

Every tool:
- takes a Pydantic model, returns a Pydantic model
- returns a typed `ToolError` instead of raising, **for a domain outcome it
  recognises** — see below
- logs `{call_id, agent, tool, args, duration_ms, result_rows, ok}`
- is idempotent if it writes

`call_id` is keyword-only with no default: a call with nothing to attribute it
to is a bug, not a valid call, the same structural rule `search_notes` applies
to `entity_id`.

### Which failures are returned, and which are raised

`tool_call` catches **only** `ToolDomainError` and its subclasses — the
address that doesn't resolve, the entity id in the wrong shape — and turns
those into a `ToolError` the caller reads like any other result.

Everything else propagates: `pydantic.ValidationError`, `KeyError`, a bare
`ValueError`. Those are defects, and a tool that answers every failure with an
equally polite `ToolError` is indistinguishable, from the outside, from a tool
with a bug in it. A traceback in a test is the cheaper outcome.

Phase 2's `knowledge` and `prose` modules keep raising bare `ValueError` for
what are really domain outcomes, and each tool translates at its own
boundary into a type in `tools/errors.py` (T3.2). The layer below is also
called directly by build steps and scripts, which want the traceback — so
the translation belongs at the edge the agent calls, not in the query.

`RetrievalUnavailableError` is the judgement call in that set: an
unreachable embeddings API is not a defect in the calling path and not
something a retry inside the tool fixes, so `search_notes` returns it
rather than raising. Mid-call the agent has to be able to say the notes
can't be searched and offer a human. The failure is still loud — `ok:
false` in the call log, and a failing test for anything asserting a real
search.

### `duration_ms` is a total, not the only timing

`duration_ms` is the source of the latency baseline from T3.1 onward, and it
is always the whole call. A tool whose budget splits across genuinely
different costs reports the breakdown too: a result overriding
`timings() -> dict[str, float]` has those keys merged into the same log
record, beside the total rather than instead of it.

`search_notes` is the case that forced this — T2.5 measured 463 ms of OpenAI
embedding call against 2-5 ms of Postgres, so one fused number is a p95 that
says nothing about which half moved. Layer 4 asserts the network leg
separately from the database leg. Most tools override nothing and log the
total alone.

See the per-tool budgets in `docs/ARCHITECTURE.md`.

## Tool kinds

| Kind | Meaning | Agent restriction |
|---|---|---|
| `SQL` | Typed read against records or derived tables | any read-path agent |
| `hybrid` | Retrieval over note prose | Service |
| `logic` | Pure computation, no data access | any |
| `web` | External network read | Service |
| `write` | **Mutates a customer record.** Dispatch only. | Dispatch |
| `control` | Changes call routing or state. Writes an audit row, touches no customer record. | any |

`control` exists so that `transfer_to_human` does not have to be a `write`.
Transferring a call mutates nothing a customer would ever see on their account;
it routes a phone call and logs why. Classifying it as a write forced it to
live on Dispatch, which would have meant a general enquiry had to reach the
write-holding agent in order to be handed to a person. The hard rule in
`CLAUDE.md` is scoped to **customer-record write tools** for the same reason.

## Tools

| Tool | Agent | Kind | Contract |
|---|---|---|---|
| `resolve_address` | Triage | SQL | Normalise spoken street, `pg_trgm` similarity over 1,337 canonical addresses. Returns up to 3 candidates with scores and **`canonical_id`**, never a source `address_id`. `must_ask=true` — ask, never guess — when the top score is below 0.55, **or** when it and the runner-up are within 0.05 of each other even if both individually clear 0.55. Returns address candidates only: no history, no balance, no appointment. |
| `resolve_customer` | Triage | SQL | By name, company, or resolved address. Same candidate + confidence shape. Returns name, `kind` and the customer record's own `job_count` — no job, invoice, note or schedule data. `kind` is unreliable — see below. Asks more often than `resolve_address` does: two different customers are both called "Starfish Hospitality", and a name that is the start of a longer one ("Lighthouse") is an ask, because trigram similarity measures length, not meaning. |
| `identify_caller_role` | Triage | logic | homeowner / property_manager / tech / owner. Determines which agent takes over and which tools exist. Takes no database session at all: every signal is passed in, including the customer fields `resolve_customer` returned. **`owner` is the company's owner**, so "I own the house" is a homeowner and "I own the company" is not. |
| `get_visit_history` | Service | SQL | Structured rows from `get_visit_history` for a **`canonical_id`**: job id, `job_number` (never `invoice_number` — joined on `job_id` only), service date, techs, description, invoice numbers, outstanding balance, and `callback_from_job_id` if this visit was a callback about an earlier one. Ordered, so "last" is a fact. No generated prose — the agent summarises at speaking time. Aggregates the 0-to-4 invoices a job may have. |
| `get_warranty_status` | Service | SQL | Derived per the precedence rule in `docs/DATA.md`, scoped to a `canonical_id` plus the equipment the caller named. **Always returns the basis and the level**, never a bare yes/no. |
| `get_customer_balance` | Service | SQL | `SUM(job.outstanding_balance)` across every job for a `customer_id` — a customer total, not scoped to an address. Zero, not an error, for a customer with no jobs. |
| `search_notes` | Service | hybrid | `search_notes(entity_id, query)`. Entity id is required and positional. Returns `note_id`, `snippet`, and **`job_service_date`**. See citation rules below. |
| `get_schedule` | Service | SQL | Today or a date range, scoped to caller role. A homeowner **or property manager** may only see their own jobs, and a request from one without a resolved `customer_id` fails validation rather than querying. `tech` and `owner` are internal and see the whole day. Excludes stale scheduled jobs — see `docs/SCOPE.md`. |
| `web_search` | Service | web | Weather, model numbers, supplier hours. Always returns the source. Try `search_notes` first for anything the company may already know. |
| `find_availability` | Dispatch | SQL | Gaps in the assumed working day, against future scheduled jobs only. Returns **one row per window** with an available tech — a caller is offered times, not a roster. Bookable techs are `role = 'field tech'` (15 of 23), read off the record rather than an exclusion list. The working day is an assumption, not data, and the caveat is carried in the result — see `docs/SCOPE.md`. |
| `book_job` | Dispatch | write | Requires explicit spoken confirmation — a required non-empty field holding **what the caller actually said**, not a bool claiming they said it. Idempotency key from `call_id + slot + address` (the address is an addition to the spec: one call booking two buildings into the same window is two appointments, not a retry — see `docs/DECISIONS.md`). Writes `ops.booked_jobs`, never `source.jobs`. Emits to the dashboard feed via the `write_audit` trigger. Returns **no job number**: the field service system assigns those. |
| `move_job` | Dispatch | write | Same rules. Key is `call_id + job_id + the new slot`. Writes an audit row with old and new values. The job itself is never mutated — the new slot is a row in `ops.job_reschedules` that `get_schedule` applies as an overlay. Works on an agent booking as readily as on a loaded job. |
| `add_note` | Dispatch | write | Appends a note attributed to the agent and the call, into `ops.agent_notes` — `source.notes` is the loaded export and `verify_load.py` asserts its 6,954 rows. Key is `call_id + job_id + content`, since a note has no slot. **No spoken confirmation:** writing down what was said changes nothing about the caller's schedule or account. |
| `transfer_to_human` | any | **control** | Logs reason, transcript, and every promise made. Writes an audit row. Mutates no customer record. Then stops. |

### Writes: idempotency, audit, and where they land (T3.3)

Every write tool derives a key from the arguments that define *the same
write*, and `ops.write_audit.idempotency_key` is `UNIQUE`. The constraint is
the guard — a lookup before the insert is a race two retries can both win. A
retry returns the original result with `replayed=true`: never an error, never
a second booking.

Nothing is written into `source`. See "Writes are an overlay" in
`docs/ARCHITECTURE.md` for why, and for the three consequences that follow
(effective staleness, no job number on an agent booking, no foreign keys from
`ops` to `source`).

Every audit row fires a `pg_notify` on `switchboard_writes` from a database
trigger, so a write cannot forget to announce itself and a rolled-back write
announces nothing.

`transfer_to_human` is `control`, not `write`. It writes an audit row when
T5.4 builds it; the table already carries it.

## Which number the agent speaks

`jobs.jsonl` has a field called `invoice_number` that is **the job number**.
Joining on it lands on another customer's invoice 1,649 times out of 1,992
(`docs/DATA.md`).

- **To the caller, the agent speaks the job number.** That is the number the
  office and the customer both use.
- An invoice number is spoken only when citing an invoice as evidence — a
  warranty line item, an outstanding balance — and is labelled as an invoice
  number when spoken, so the two never blur on a recorded call.
- Internally, `job_id` is the only join key. Nothing joins on a number.

## Citing a note

Notes have no timestamp. A note is `{id, content}` and nothing else.

Any date attached to a note is the **service date of the job it belongs to**.
`search_notes` returns it as `job_service_date`, and the agent must speak it as
such: "from the visit on 14 June", never "a note from 14 June". Ordering within
a job is the array order and is only roughly chronological; it is not a
timestamp and must never be presented as one.

## `customer.kind` is not a role signal

`kind` is `homeowner` or `business` — not "company", as `data/README.md` says —
and it does not track reality. 31 customers marked `homeowner` have a `company`
set, 14 marked `business` do not, and 48 marked `homeowner` are plainly
businesses. "Lighthouse Hospitality" is stored in `first_name` / `last_name`.

`identify_caller_role` must not branch on `kind` alone. It combines the name
and company fields, the job count, and what the caller says. When the signals
disagree, it asks.

## Refusal rules

- `resolve_address` below 0.55, or two candidates within 0.05 of each other,
  are both "ask" — a caller who trails off before the house number can leave
  two real addresses individually confident and jointly indistinguishable, and
  that is not a case for a guess either. See `docs/DECISIONS.md`.
- Warranty answers at **levels 4, 5 and 6** of the precedence rule are spoken
  as uncertain and offered for human check. Levels 1, 2 and 3 are stated as
  facts with their basis. Level 2 is stated as historical: the part *was*
  covered on that visit, which is not the same as covered today.
- `Warranty Complete` is **never** spoken as a denial of coverage. It records
  that warranty work was completed. It is level 5, neutral.
- No write without a spoken confirmation in the same turn sequence.
- No answer about another customer's property, ever, regardless of what the
  caller claims.
- No job, invoice, note or schedule data before identity is resolved. This is
  the Triage boundary in `docs/ARCHITECTURE.md` and it is asserted by Layer 3b.
- If no tool grounds the answer, say so and offer transfer. Refusing is a
  correct output.
