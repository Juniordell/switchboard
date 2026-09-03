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
| Cross-encoder reranking | Retrieval is scoped to a resolved entity, so candidate sets are ~3 rows. Reranking them is latency spent for nothing. |
| Reconciler and Dispatcher async agents | Extractor and Reviewer demonstrate the pattern and the human boundary. The other two are the same idea repeated. |
| LangChain, MLflow | No orchestration wrapper is needed over a framework that already orchestrates, and nothing here trains a model. |
| Vector database | 1.5 MB of prose. Postgres is sufficient and one less service to deploy. |

## Known limitations

- The provided calendar has only 42 jobs scheduled after 2 September 2026, so
  availability is computed as gaps in a tech's working day rather than from a
  dense booking table.
- Phone numbers and emails are redacted in the dataset, so callers cannot be
  identified by caller ID. Identity is established in conversation.
- Warranty status is derived, not authoritative. The basis for every answer is
  returned alongside it so a human can check.