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

## Tools

| Tool | Agent | Kind | Contract |
|---|---|---|---|
| `resolve_address` | Triage | SQL | Normalise spoken street, `pg_trgm` similarity over 1,188 addresses. Returns up to 3 candidates with scores. Below 0.55 → agent must ask, never guess. |
| `resolve_customer` | Triage | SQL | By name, company, or resolved address. Same candidate + confidence shape. |
| `identify_caller_role` | Triage | logic | homeowner / property_manager / tech / owner. Determines which agent takes over and which tools exist. |
| `get_visit_history` | Service | SQL | One row from `visit_history` for an address id: dates, techs, invoice numbers, balances, pre-summarised. Ordered, so "last" is a fact. |
| `get_warranty_status` | Service | SQL | Derived per the precedence rule in `docs/DATA.md`. **Always returns the basis**, never a bare yes/no. |
| `search_notes` | Service | hybrid | `search_notes(entity_id, query)`. Entity id is required and positional. Returns note id, date, snippet for citation. |
| `get_schedule` | Service | SQL | Today or a date range, scoped to caller role. A homeowner may only see their own jobs. |
| `web_search` | Service | web | Weather, model numbers, supplier hours. Always returns the source. Try `search_notes` first for anything the company may already know. |
| `find_availability` | Dispatch | SQL | Gaps in techs' working days, not existing bookings. Returns slot windows with tech names. |
| `book_job` | Dispatch | write | Requires explicit spoken confirmation. Idempotency key from `call_id + slot`. Emits to the dashboard feed. |
| `move_job` | Dispatch | write | Same rules. Writes an audit row with old and new values. |
| `add_note` | Dispatch | write | Appends a note attributed to the agent and the call. |
| `transfer_to_human` | any | write | Logs reason, transcript, and every promise made. Then stops. |

## Refusal rules

- Warranty answers below confidence 3 in the precedence list are spoken as
  uncertain and offered for human check.
- No write without a spoken confirmation in the same turn sequence.
- No answer about another customer's property, ever, regardless of what the
  caller claims.
- If no tool grounds the answer, say so and offer transfer. Refusing is a
  correct output.