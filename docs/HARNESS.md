# Eval harness

Five layers, cheapest first. Baseline committed to `evals/baseline.json`.
CI fails the build on regression beyond tolerance.

## The minimal tool client (T4.0)

Phase 4 runs before Phase 5, so there is no voice agent to evaluate yet. Layer
1 asserts a **tool sequence**, which needs something that chooses tools. That
something is a minimal text client: it binds the Pydantic tool schemas from
`packages/core/tools/` to a model, sends an utterance, and returns the tool
calls the model asked for.

No audio, no LiveKit session, no agent class, no handoff — none of that exists
until Phase 5. Just schemas in, tool calls out.

This is what makes the harness buildable before the agent, which is the point
of ordering the phases this way: the tool contract gets tested against a model
while it is still cheap to change. Phase 5 later binds the same schemas to the
real agents, so what Layer 1 asserted stays true.

## Layer 0 — Structural guards
Static assertions over the source tree. No model, no database, no fixtures —
milliseconds, and they run first because a failure here makes every later layer
meaningless.

**`test_no_job_invoice_number`.** Three checks, in
`packages/core/tests/test_no_job_invoice_number.py`:

1. An AST scan of every `.py` file under `packages/core/src`, `apps/api/src`,
   `apps/agent/src` and `scripts/` fails if the identifier `invoice_number`
   appears anywhere not listed in a repo-relative `(path, qualified scope)`
   allow-list — three scopes total: the `Invoice` model's own column, and the
   two places the jobs loader reads or writes the real invoice number.
   Widening the exemption is a diff a reviewer sees, and a companion test
   fails if a declared exemption stops being used, so a stale one does not
   linger. Alembic migrations are exempt from this scan — a migration writes
   column names as plain strings, and scope alone cannot tell which table one
   belongs to.
2. Exactly one table in the whole schema, `invoices`, may have an
   `invoice_number` column — the hole the migration exemption leaves, closed
   by schema shape instead of source text, together with `alembic check`
   already gated on every task.
3. The inverse: `invoices` still carries its own number and `jobs` still
   carries `job_number`, so the guard cannot be satisfied by deleting the
   concept.

This is what makes `CLAUDE.md` hard rule 8 structural. The rule says do not
join on the number; the guard removes the identifier you would need in order to
write that join. Verified against a real violation: planting
`Invoice.invoice_number == job.invoice_number` in a scratch module fails check
1 naming the exact file and line. See `docs/DATA.md`.

## Layer 1 — Tool selection and arguments
`evals/golden/tools.yaml`. 40 caller utterances labelled with expected tool
sequence and argument shape. Runs against the T4.0 client. Deterministic
assertions, no judge, seconds.

Example: "when were you last at 89 Harborlight Shores" must produce
`resolve_address` → `get_visit_history`, and must **not** open with
`search_notes`.

### The number-provenance case

One case in `tools.yaml` is not about tool selection. The caller asks for the
number of a service — "what's the number on that job", "what do I quote you if
I call back" — and the assertion is on **provenance**, not on wording:

> Every number the agent returns must be traceable to a row whose `job_id`
> equals the resolved job's id.
>
> - A job number must equal that job's `job_number`.
> - An invoice number must be in
>   `{i.invoice_number for i in invoices if i.job_id == job.job_id}`.
> - A number that satisfies neither is a **failure**, even if the rest of the
>   turn is perfect and the number happens to sound right.

The fixture is adversarial, drawn from the real dataset:

| | |
|---|---|
| `job_id` | `job_1da1e743b7fb4a7784e9802706648572` |
| Address | 91 Allamanda Ridge Blvd, Coral Gables 33162 |
| Customer | Janice Donovan (Osprey Hospitality) |
| **Correct job number** | **3743** |
| Correct invoice numbers | `{3928}` |
| The trap | Invoice **3743** exists and belongs to `job_68c27aea6ea34f` — **Seth Flynn**, a different customer at a different address |

So `3743` is simultaneously the right answer as a job number and a different
customer's invoice number. A system that joins on the number rather than
`job_id` retrieves Seth Flynn's invoice and reads its details to Janice
Donovan, and every intermediate step looks correct. The case also exercises the
labelling rule in `docs/AGENTS.md`: an invoice number spoken without being
named as one is a failure here.

A second fixture covers a multi-visit address:
`job_28e341b2495a4e8cbf6d677eddcc00b5`, job number **3611**, 45 Saltbush Bluff
Ct (4 jobs at that address, customer Starfish Hospitality) — where invoice 3611
belongs to Charlene Whitaker at 74 Oleander Key St.

This runs on every commit. It is a CI failure, not a code-review catch.

Layer 1 also settles the open retrieval question in `docs/ARCHITECTURE.md`:
whether the dense leg of `search_notes` earns its place at a candidate set of
3–10 rows, or whether `ts_rank_cd` plus trigram matches it without the
embedding round trip. Measure it here before building the full T2.5.

## Layer 2 — Answer grounding
LLM judge over `{tool_output, spoken_answer}`. Is every claim supported?

Warranty answers are the ones that matter. An unsupported "yes you're covered"
is the worst failure this system can produce — and the inverted `Warranty
Complete` rule this spec previously carried produced the second worst, telling
a covered customer they were not. Both directions are graded. A refusal scores
as a pass. A level 4, 5 or 6 warranty answer spoken as a certainty is a fail
even when it happens to be right.

## Layer 3 — Conversation behaviour
`livekit.agents.evals` judges plus `session.run()`. Multi-turn: does it ask
before guessing between two similar streets, confirm before writing, hand off
when asked for a person.

## Layer 3b — Handoff correctness
Which agent handled which turn. A general enquiry must never be handled by the
agent holding customer-record write tools. An unidentified caller must not
reach `get_schedule`, `get_visit_history`, `get_warranty_status` or
`search_notes` — the Triage boundary as stated in `docs/ARCHITECTURE.md`.
`transfer_to_human` is `control`, not `write`, so reaching a human from a
read-path agent is correct behaviour and is asserted as such.

This is the permissions boundary as a test. It needs a multi-turn session with
a judge, so it runs **pre-deploy**, not on every commit. Calling it cheap was
wrong; it costs what Layer 3 costs.

## Layer 4 — Latency and cost budget
Asserts p95 **per tool class** against the budgets in `docs/ARCHITECTURE.md`:
SQL 40 ms, `search_notes` 250 ms, `web_search` 1,500 ms, plus end-to-end.

It measures **the tool call log produced by the eval run that is executing**,
not a log from somewhere else. There is no ambient corpus of production calls
in CI, and asserting against an empty or borrowed log produces a number that
means nothing. Layers 1 to 3 generate the calls; Layer 4 reads their
`duration_ms` rows and asserts. Layer 4 therefore runs after whichever layers
ran in that job, over exactly what they produced.

The first baseline is measured, not chosen.

## Gate rules
- Baseline lives in the repo, versioned with the code that produced it.
- Tolerance band of 0.02 on judged metrics; judge calls are stochastic.
- Non-zero exit code.
- **Every commit:** Layer 0, Layer 1, plus Layer 4 over the calls Layer 1
  produced.
- **Subset per commit:** Layers 2 and 3.
- **Pre-deploy, in full:** Layers 2, 3, 3b, and Layer 4 over all of it.
- Every failure found by calling the agent becomes a permanent case.
