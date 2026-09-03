# Scope

48-hour build. The assignment says the spec describes more than expected and
should not be treated as a checklist, so this file records what was chosen and
what was deliberately left out.

## In scope

- Inbound voice agent on a real US phone number.
- Company knowledge: visit history, warranty status, schedules, invoices, notes.
- A live web tool for questions the data cannot answer.
- Write actions: book, move, add note. Confirmed on the call, approval-gated,
  audited.
- Handoff to a human with a contextual summary.
- Operations platform: today view, call log with transcript and tool calls,
  live action feed while the call is in progress, job and address detail.
- Async back-office agents that run after a call and file proposals into a
  human review queue.
- Eval harness with a CI gate.

## Out of scope, and why

| Excluded | Reason |
|---|---|
| Authentication | Single-tenant demo. A day of work that demonstrates nothing about the problem being tested. |
| Outbound calling | Nothing in the brief needs it. Every complaint the owner raised is inbound. |
| iOS / mobile | Named as a stretch area in the job description, not in this assignment. |
| Real-audio eval suite | Requires a dedicated platform. Text-only evals miss telephony, accents and noise; this is the first thing I would add next. |
| Cross-encoder reranking | Retrieval is scoped to a resolved entity, so candidate sets are 3–10 rows. Reranking them is latency spent for nothing. |
| **Reconciler** and **Dispatcher** async agents | Both are defined in `docs/ARCHITECTURE.md`. Extractor and Reviewer demonstrate the pattern and the human boundary; Reconciler is the same post-hoc comparison against a different source of truth, and Dispatcher needs a scheduling model the dataset cannot support (see the working-day assumption below). Defined so the topology is legible, not built. |
| LangChain, MLflow | No orchestration wrapper is needed over a framework that already orchestrates, and nothing here trains a model. |
| Vector database | 1.54 MB of prose. Postgres is sufficient and one less service to deploy. |

## The working day is an assumption, not data

**The dataset contains no working hours.** There is no shift table, no
availability, no time-off, no business hours — nothing that says when a tech
can be booked. `find_availability` is specified as "gaps in techs' working
days", and the working day has to be invented. This is the largest unbacked
assumption in the build and it is stated here rather than buried in a constant.

What the data does say, from 1,898 jobs with a `scheduled_start`, in
`America/New_York` (the only timezone in the dataset, on all 1,992 rows):

| Window | Coverage of historical starts |
|---|---|
| Mon–Fri 08:00–18:00 | 77.1% |
| **Mon–Sat 08:00–18:00** | **83.0%** |
| Any day 08:00–18:00 | 87.0% |

Starts peak at 10:00 (343 jobs) and taper to 22:00 (5 jobs). Saturday carries
157 jobs and Sunday 108, so weekends are worked, lightly. `arrival_window` is
120 minutes on 1,874 of 1,992 jobs.

**The rule chosen:**

- Bookable window: **Monday to Saturday, 08:00–18:00 America/New_York.**
- Slot granularity: **120-minute arrival window**, matching the dominant
  historical value.
- Sunday and after-hours are **not offered by the agent**. The 108 historical
  Sunday jobs are emergency work; a caller asking for one is transferred to a
  human rather than booked into an assumption.
- Occupancy is computed against **future `scheduled` jobs only** — 38 rows
  across 2026-09-02 to 2026-09-15, using 11 of the 15 field techs.
- "Team Phone" (`pro_11d5d0c713334f2cbb2ee822abb8e200`, office staff) is
  excluded from availability. It is the shared office line, not a person.
  So are the 6 admin and the other office staff row: 15 field techs are
  bookable.

The rule covers 83% of how this company has actually scheduled work. Every slot
the agent offers is therefore a proposal against an assumed calendar, and the
booking confirmation says so.

### Stale scheduled jobs

76 jobs carry `work_status = scheduled`. Only **38 are in the future**. The
other 38 are dated 2026-03-07 to 2026-08-30, none has a `completed_at`, and 15
carry a partial work timestamp. They are abandoned rows.

**The rule:** a `scheduled` job whose `scheduled_start` is in the past is
**stale**. Stale jobs are excluded from the today view, excluded from
availability occupancy, and are never spoken as an upcoming appointment. They
appear only in an explicit "stale" bucket on the operations dashboard, because
38 forgotten jobs is exactly the kind of thing the owner would want surfaced.

The 94 jobs with no `scheduled_start` at all are never stale and never
scheduled; they sort last and are shown as unscheduled.

## Known limitations

- The provided calendar is nearly empty going forward: **38 scheduled jobs**
  after 2 September 2026, the last on **2026-09-15**. (`data/README.md` claims
  the calendar runs through the end of the year. It does not.) Availability is
  therefore computed as gaps in the assumed working day above, not from a dense
  booking table.
- Phone numbers and emails are redacted in the dataset, so callers cannot be
  identified by caller ID. Identity is established in conversation.
- Warranty status is derived, not authoritative, and the source signals
  disagree. The basis and the precedence level are returned alongside every
  answer so a human can check.
- Notes have no timestamps. Every note is dated by its job's service date and
  is spoken that way. See `docs/DATA.md`.
- `customer.kind` does not reliably distinguish a homeowner from a business, so
  caller role is established in conversation rather than read off the record.
