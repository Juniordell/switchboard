# Decisions

Decisions taken without being told to take them, and why. One line each.

If a decision was instructed, it is not here — it is in the commit that made
it. This file exists for the other kind: the judgement calls made while
carrying out an instruction, where six weeks later the reasoning is gone and
only the artefact remains. Including the ones that overrode a number or a rule
someone else supplied, which are marked **override**.

Newest last. Dates are when the decision was made, not when it was written down.

## 2026-09-03 — Spec correction pass

| # | Decision | Why | Lives in |
|---|---|---|---|
| 1 | Work on branch `phase-0-specs` rather than `main` | CLAUDE.md forbids committing to main; phase branches are the stated convention and this is the pre-implementation phase | git |
| 2 | **Override:** canonical address count is **1,360**, not the 1,367 supplied | 1,367 is not reproducible under any normalisation I could construct; 1,360 is what the agreed canonical key actually produces | DATA.md |
| 3 | **Override:** **30** split address groups, not the 25 supplied, by excluding `city` from the canonical key | The two supplied numbers contradicted each other — 25 requires city in the key; the anonymisation gives zip 33162 seven city names, so city is noise and the 5 extra merges are genuine | DATA.md, ARCHITECTURE.md |
| 4 | Warranty line-item filter is `ILIKE '%warrant%'`, with 3 named exceptions | The supplied count of 64 only holds case-insensitively; the exact prefix matches 61 and silently loses 3 covered parts | DATA.md |
| 5 | Working day = **Mon–Sat 08:00–18:00 ET, 120-minute window**, Sunday transfers to a human | Asked to choose a rule; picked by measurement — covers 83% of historical starts vs 77% for Mon–Fri, and 120 min is the arrival window on 1,874 of 1,992 jobs. Sunday's 108 jobs are emergency work, so booking one against an assumed calendar is worse than transferring | SCOPE.md |
| 6 | Stale jobs are hidden from the today view and availability but surfaced in their own dashboard bucket | Asked to choose; hiding them entirely loses information the owner would want, and 38 forgotten jobs is exactly the kind of thing this platform exists to show | SCOPE.md, DATA.md |
| 7 | Wrote the content of all four async agents, including the two not being built | Asked to define them; the definitions had to be specific enough that excluding two reads as a choice rather than an omission | ARCHITECTURE.md |
| 8 | Latency stated as a 730 ms fixed cost plus per-tool budgets, rather than one table | The single number hid that a retrieval turn and an indexed lookup are different operations; separating them is what makes `search_notes` at 250 ms an honest budget instead of a failed one | ARCHITECTURE.md |
| 9 | Left the dense-vs-lexical question for `search_notes` open, routed to T4.2 as a measurement | At 3–10 candidate rows the dense leg may not be earning the embedding round trip, but guessing either way costs more than measuring once | ARCHITECTURE.md, HARNESS.md |
| 10 | Split T2.3 into T2.3a (derived install date) and T2.3b (precedence rule) | Asked for install date as its own task; the precedence rule cannot be built before it, and one task hiding a dependency is how the dependency gets skipped | TASKS.md |
| 11 | Introduced a `control` tool kind rather than special-casing `transfer_to_human` | Told to reclassify the tool; a named kind makes the next routing-but-not-writing tool obvious, where an exception would have to be re-argued | AGENTS.md |

## 2026-09-03 — The join trap

| # | Decision | Why | Lives in |
|---|---|---|---|
| 12 | The join rule is **hard rule 8 in CLAUDE.md**, not only a section in DATA.md | DATA.md is read when someone is thinking about data; CLAUDE.md is in context on every turn. This is the one error in the dataset that reads another customer's record aloud over the phone while every intermediate step looks correct, so it has to be present at the moment the code is written, not at the moment the data is studied. Flagged for veto when made; kept | CLAUDE.md |
| 13 | Appended as rule 8 rather than inserting after rule 2 where it belongs topically | The instruction that prompted it referenced "hard rule 4" by number; renumbering would have invalidated that reference and every other one in flight | CLAUDE.md |
| 14 | `invoice_number` is contained inside the loader function rather than merely renamed at the boundary | Told to rename it; a rename still leaves the identifier available to type. Containment means there is no `job.invoice_number` to put on either side of an `==`, so the wrong join is unwritable rather than forbidden | DATA.md |
| 15 | Enforcement is an **AST guard** with the loader allow-listed by qualified name, plus an inverse assertion | A grep would be defeated by a rename; the allow-list makes widening the exemption a visible diff, and asserting `invoices` keeps its own `invoice_number` stops the guard being passed by deleting the concept | HARNESS.md, TASKS.md |
| 16 | The guard became **Layer 0**, a new harness layer, rather than a case inside Layer 1 | It needs no model, no database and no fixtures, and a failure makes every later layer meaningless — that is a different tier, not a cheaper case | HARNESS.md |
| 17 | The golden case asserts **provenance**, not wording | Asked for a test that fails when the number does not belong to the job; asserting the spoken string is brittle and would pass a right-sounding wrong number | HARNESS.md |
| 18 | Fixture `job_1da1e743…` chosen from 613 adversarial candidates | It is the only shape where the correct job number and a different customer's invoice number are the same digits (3743), so it also exercises the rule that invoice numbers must be labelled when spoken | HARNESS.md |
| 19 | Declined to write `packages/core` models and the golden file when asked | Both targets were empty directories with no workspace, ruff or pytest behind them; code that cannot run cannot break CI, which was the point of the request. Recorded as binding spec and scheduled at T1.3a and T4.1 instead | TASKS.md |
| 20 | This file, and the CLAUDE.md line that keeps it fed | Told to keep the log; putting the obligation in CLAUDE.md is what makes it survive a session boundary, since nothing else carries it forward | DECISIONS.md, CLAUDE.md |
