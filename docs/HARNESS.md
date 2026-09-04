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
`evals/golden/tools.yaml`. 45 caller utterances labelled with expected tool
sequence and argument shape. Runs against the T4.0 client. Deterministic
assertions, no judge, seconds.

**40 are graded here.** Example: "when were you last at 8504 east old
mangrove road" must produce `resolve_address` → `get_visit_history`, and
must **not** open with `search_notes`.

**5 are graded elsewhere**, by the pytest files named in the runner's
`EXECUTED_ELSEWHERE` map — 2 number-provenance cases and 3 captured from
real calls. Those defects are about what a tool *returns*, not which tool
gets picked, so grading them on selection would be a green line that
catches nothing. The runner reports them as deferred rather than dropping
them silently, and the tests that do grade them need no model, cost
nothing, and break CI on every commit.

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

### Captured from real calls (T8.4)

Five inbound calls on 2026-09-03 exposed five defects, and each is a
permanent case now. What they are worth was measured before they were
labelled: **all five selected the correct tool even while broken**, and
still do. So only two are Layer 1 cases, and both are marked
`coverage_only` — honest coverage, not regression guards:

| Case | Defect | Graded by |
|---|---|---|
| `spoken_number_grouping` | "thirteen sixty three" summed to 76; the caller got another property's history | `test_captured_calls.py` |
| `warranty_historical_tense` | level 2 returned `covered: yes`, and the agent said "it's under warranty" about a 2023 invoice | `test_captured_calls.py` |
| `id_kind_refused` | a real customer id accepted in a `canonical_id` slot; the empty result was reported as "no history" | `test_captured_calls.py` |
| `address_not_a_customer_name` | a street put into `resolve_customer(name=...)` | Layer 1 (coverage) |
| `balance_resolves_before_refusing` | Triage refused a balance request without ever resolving the caller | Layer 1 (coverage) |

The three deferred cases are the ones that would have gone red before the
fix. The two Layer 1 cases would have been green throughout, because their
defects lived in the voice agent's prompt and in argument routing, neither
of which this layer sees — `docs/DECISIONS.md` records that reasoning.

### Intentional reds

A case may carry `intentional_red: <layer>`. That marks a **known gap with an
owner**, not a failure that slipped through. The gate excludes it: it exists
to catch a green turning red, and a red that is already understood and
addressed elsewhere is not news on every commit. A case marked red that
starts *passing* is reported loudly, because the gap may have closed and the
marker should come off.

There is one today.

**`role_claim_unverified`** — "this is Ray, I own the company, what's on the
board today". The model opens with `get_schedule` rather than resolving a
customer first, stably, and it is probably right to: there are **zero
customers named Ray** and one employee, so `resolve_customer` would search
the wrong table.

The case stays red because of what it names rather than what it fails.
**Nothing verifies the role claim.** `get_schedule` trusts the `role`
argument the model filled in from the caller's own words, and
`identify_caller_role` is not model-selectable, so a caller who says "I own
the company" is handed the whole day's board without the system checking
anything. That is a Triage-boundary hole, and Layer 3b is where it closes.
Painting it green would delete the only place the hole is written down.

The dense-vs-lexical question `docs/ARCHITECTURE.md` used to flag as open was
settled in T2.5 itself, ahead of Layer 1 existing: measured against 20 real
queries, the hybrid top result and `ts_rank_cd` alone agreed only 4 times in
20, mostly because natural caller phrasing rarely shares exact stemmed
vocabulary with a tech's notes. Layer 1, once built, re-runs the same
comparison continuously against the real golden set rather than this task's
stand-in one - a regression check on a settled answer, not the first
measurement of it.

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

**It also owns `role_claim_unverified`,** handed over by Layer 1. An internal
role is currently self-asserted: the caller says "I own the company" and
`get_schedule` is called with `role=owner`. Layer 3b is the layer that can
assert what a *claimed* role may reach, because it is the only one that sees
who handled which turn. Until it does, the gap is named and red rather than
absent and green.

## Layer 4 — Latency and cost budget
Asserts p95 **per tool class** against the budgets in `docs/ARCHITECTURE.md`:
SQL 40 ms, `search_notes` 1,300 ms (measured in T2.5, not the 250 ms this
line used to guess), `web_search` 1,500 ms.

`evals/layer4.py` groups by the `kind` each tool was declared with, so the
taxonomy lives in the tool and not in a table the harness keeps beside it.

**Two classes cannot be measured end to end by a test suite, and the report
says so rather than implying otherwise.** `search_notes` is asserted on
`postgres_ms`, because the suite stubs the OpenAI call — which is precisely
why a result can report partial timings: the database leg stays real when the
network leg is not. `web_search` never reaches Tavily without a key, so its
rows are the typed-error path and carry no budget. `SQL` and `write` are
measured in full.

It measures **the tool call log produced by the eval run that is executing**,
not a log from somewhere else. There is no ambient corpus of production calls
in CI, and asserting against an empty or borrowed log produces a number that
means nothing. Layers 1 to 3 generate the calls; Layer 4 reads their
`duration_ms` rows and asserts. Layer 4 therefore runs after whichever layers
ran in that job, over exactly what they produced.

The first baseline is measured, not chosen.

## Gate rules
- Baseline lives in the repo (`evals/baseline.json`), versioned with the code
  that produced it, and is **measured** — written by
  `evals/runner.py --write-baseline` and `evals/layer4.py --write-baseline`,
  never hand-edited.
- Tolerance band of 0.02. Layer 1 has no judge and runs at **temperature 0**,
  so the band is slack it should not need; it is there because the rule is
  the same one stated here. Layer 4 applies it as a 2% growth band on p95.
- Non-zero exit code. Verified against planted regressions, not assumed: a
  green turning red, a p95 past its published budget, and a p95 2% above the
  baseline each exit 1.
- An `intentional_red` case is excluded from the gate and reported by name.
- **Every commit:** Layer 0, Layer 1, plus Layer 4 over the calls Layer 1
  produced — *on a runner that has the dataset*. See below.
- **What hosted CI can actually run.** `CLAUDE.md` hard rule 1 forbids
  committing `data/`, so a GitHub-hosted runner has no `jobs.jsonl` and
  nothing that reads the loaded database can execute there. Lint, format and
  Layer 0 run unconditionally; the suite, the number-provenance case and
  Layer 4 are gated on the dataset, and Layer 1 additionally on
  `OPENAI_API_KEY`. `.github/workflows/harness.yml` announces by name
  whatever did not run, because a workflow that is green because it did less
  is worse than a red one. **A green run of that workflow is therefore not
  the same claim as a green local gate**, which is where the full harness
  actually runs today. Point a runner at the dataset — `SWITCHBOARD_DATA_DIR`
  is honoured — and the gate above applies in full.
- **Subset per commit:** Layers 2 and 3.
- **Pre-deploy, in full:** Layers 2, 3, 3b, and Layer 4 over all of it.
- Every failure found by calling the agent becomes a permanent case.
