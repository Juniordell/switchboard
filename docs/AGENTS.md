# Agents and tools

All tools live in `packages/core/tools/`. They are ordinary typed Python
functions with Pydantic argument models. The voice agent binds them; the
FastAPI app exposes them; the async agents import them. One implementation.

## Tool contract

Every tool:
- takes a Pydantic model, returns a Pydantic model
- never raises to the caller; returns a typed error result
- logs `{call_id, agent, tool, args, duration_ms, result_rows, ok}`
- is idempotent if it writes

`duration_ms` is the source of the latency baseline from T3.1 onward. See the
per-tool budgets in `docs/ARCHITECTURE.md`.

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
| `resolve_address` | Triage | SQL | Normalise spoken street, `pg_trgm` similarity over 1,360 canonical addresses. Returns up to 3 candidates with scores and **`canonical_id`**, never a source `address_id`. Below 0.55 → agent must ask, never guess. Returns address candidates only: no history, no balance, no appointment. |
| `resolve_customer` | Triage | SQL | By name, company, or resolved address. Same candidate + confidence shape. Returns name and kind only. `kind` is unreliable — see below. |
| `identify_caller_role` | Triage | logic | homeowner / property_manager / tech / owner. Determines which agent takes over and which tools exist. |
| `get_visit_history` | Service | SQL | Structured rows from `visit_history` for a **`canonical_id`**: service date, tech, description, job number, invoice numbers, outstanding balance. Ordered, so "last" is a fact. No generated prose — the agent summarises at speaking time. Aggregates the 0-to-4 invoices a job may have. |
| `get_warranty_status` | Service | SQL | Derived per the precedence rule in `docs/DATA.md`, scoped to a `canonical_id` plus the equipment the caller named. **Always returns the basis and the level**, never a bare yes/no. |
| `search_notes` | Service | hybrid | `search_notes(entity_id, query)`. Entity id is required and positional. Returns `note_id`, `snippet`, and **`job_service_date`**. See citation rules below. |
| `get_schedule` | Service | SQL | Today or a date range, scoped to caller role. A homeowner may only see their own jobs. Excludes stale scheduled jobs — see `docs/SCOPE.md`. |
| `web_search` | Service | web | Weather, model numbers, supplier hours. Always returns the source. Try `search_notes` first for anything the company may already know. |
| `find_availability` | Dispatch | SQL | Gaps in the assumed working day, against future scheduled jobs only. Returns slot windows with tech names. The working day is an assumption, not data — see `docs/SCOPE.md`. |
| `book_job` | Dispatch | write | Requires explicit spoken confirmation. Idempotency key from `call_id + slot`. Emits to the dashboard feed. |
| `move_job` | Dispatch | write | Same rules. Writes an audit row with old and new values. |
| `add_note` | Dispatch | write | Appends a note attributed to the agent and the call. |
| `transfer_to_human` | any | **control** | Logs reason, transcript, and every promise made. Writes an audit row. Mutates no customer record. Then stops. |

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
