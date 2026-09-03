# Eval harness

Four layers, cheapest first. Baseline committed to `evals/baseline.json`.
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

## Layer 1 — Tool selection and arguments
`evals/golden/tools.yaml`. 40 caller utterances labelled with expected tool
sequence and argument shape. Runs against the T4.0 client. Deterministic
assertions, no judge, seconds.

Example: "when were you last at 89 Harborlight Shores" must produce
`resolve_address` → `get_visit_history`, and must **not** open with
`search_notes`.

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
- **Every commit:** Layer 1, plus Layer 4 over the calls Layer 1 produced.
- **Subset per commit:** Layers 2 and 3.
- **Pre-deploy, in full:** Layers 2, 3, 3b, and Layer 4 over all of it.
- Every failure found by calling the agent becomes a permanent case.
