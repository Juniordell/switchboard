# Eval harness

Four layers, cheapest first. Baseline committed to `evals/baseline.json`.
CI fails the build on regression beyond tolerance.

## Layer 1 — Tool selection and arguments
`evals/golden/tools.yaml`. 40 caller utterances labelled with expected tool
sequence and argument shape. Deterministic, no judge, milliseconds.
Example: "when were you last at 89 Harborlight Shores" must produce
`resolve_address` → `get_visit_history`, and must **not** open with
`search_notes`.

## Layer 2 — Answer grounding
LLM judge over `{tool_output, spoken_answer}`. Is every claim supported?
Warranty answers are the ones that matter; an unsupported "yes you're covered"
is the worst failure this system can produce. A refusal scores as a pass.

## Layer 3 — Conversation behaviour
`livekit.agents.evals` judges plus `session.run()`. Multi-turn: does it ask
before guessing between two similar streets, confirm before writing, hand off
when asked for a person.

## Layer 3b — Handoff correctness
Which agent handled which turn. A general enquiry must never be handled by the
agent holding write tools. An owner-only question from an unidentified caller
must not reach the schedule tools. This is the permissions boundary as a test.

## Layer 4 — Latency and cost budget
Assert p95 per tool and end-to-end against `docs/ARCHITECTURE.md` budgets,
computed from the tool call log.

## Gate rules
- Baseline lives in the repo, versioned with the code that produced it.
- Tolerance band of 0.02 on judged metrics; judge calls are stochastic.
- Non-zero exit code. Layers 1, 3b and 4 on every commit; 2 and 3 on a subset
  per commit and in full pre-deploy.
- Every failure found by calling the agent becomes a permanent case.