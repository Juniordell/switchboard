# The dataset

Six months of one HVAC company's records, exported from Housecall Pro.
March–September 2026. Names, addresses and amounts are anonymised consistently.
`[phone]`, `[email]`, `[code]` are redaction markers, not values.

Load from `.jsonl`. Money is in **cents** in the `.jsonl` files and dollars in
the `.csv` mirrors. The mirrors are exact (`usd == cents / 100` on every row);
they are for reading, not for loading. They sit in `data/*.csv`, not in
`data/csv/` as `data/README.md` claims.

### `data/README.md` is wrong in three places

It ships with the dataset and is not authoritative. **Where it disagrees with
the files, the files win**, and the divergence is recorded here as a trap.

| README says | The files say |
|---|---|
| CSVs are in `csv/` | They are in `data/*.csv`, flat |
| The calendar runs "through the end of the year" | The last scheduled job is 2026-09-15 |
| `taxes`, `discounts`, `payments` are "amounts only" | True of `discounts`. **`payments` carries eight fields**: `id`, `status`, `payment_method`, `amount`, `note`, `paid_at`, `category`, `surcharge_fee_amount` |

The payments one is the trap that costs something. A loader written from the
README would keep `amount` and silently drop the payment method, the surcharge
and the paid date — and "how did they pay" is a question a caller asks. All
eight are loaded; see `source.invoice_payments`.

`invoices[].taxes` is empty across all 1,700 invoices. It is still modelled, on
the general rule for the source layer: **no field from the `.jsonl` is dropped,
including fields that are empty in this export.** A loader that skips an
always-empty array keeps skipping it when a later export fills it. Its column
shape is inferred from `discounts`, the only other amount-only array, and that
inference is written down in the model rather than assumed.

## Measured shape

Every number below was counted from `data/*.jsonl`.

| Fact | Value |
|---|---|
| Jobs | 1,992 |
| Notes | 6,954 (median 120 chars, p95 801, max 10,076) |
| Total note text | ~1.54 MB |
| Invoices / line items | 1,700 / 4,390 |
| Customers | 732 — **683 `homeowner`, 49 `business`** |
| Jobs by customer kind | 1,638 homeowner, 354 business |
| Employees | 23 — 15 field tech, 6 admin, 2 office staff |
| Address ids | 1,390 distinct, **4 jobs carry `address.id = null`** |
| Address tuples | **1,367** distinct in `customer_addresses`; 1,370 raw over jobs; **1,360 canonical** (see below) |
| Distinct street strings | 1,178 |
| Scheduled after 2026-09-02 | 42 rows, of which **38 `scheduled`** + 2 `pro canceled` + 2 `user canceled` (last: 2026-09-15) |

The customer split and the job split are different numbers over different
things. 683/49 counts customers; 1,638/354 counts jobs. Do not assert one
against the other.

## Known gaps and dirty edges

Counted, not estimated. Loaders and derived tables must survive all of these.

| Gap | Count | Consequence |
|---|---|---|
| Jobs with no invoice | 456 | `job → invoice` is not total. Balances must tolerate zero rows. |
| Jobs with more than one invoice | 135 (max **4**) | `job → invoice` is not 1:1. `visit_history` aggregates. |
| Jobs with `scheduled_start = null` | 94 | Any date sort must place these deliberately, not accidentally. |
| Jobs with no assigned employee | 95 | "Which tech was here" has no answer for these. |
| Jobs with `address.id = null` | 4 | A NOT NULL FK on address id drops them. Canonical key does not. |
| `work_status = scheduled` in the past | 38 | See "Stale scheduled jobs" below. |
| Distinct tags | 23 | Includes `ACTIVE LEAK` **and** `ACTIVE LEAK\`, and `3 Tankless\`. Trailing backslashes are data, not escaping. Exact-match tag filters must handle them. |
| Notes with no timestamp | **all 6,954** | A note is `{id, content}`. Nothing else. See "Notes have no date". |

Where `job → invoice` is 1:1, `job.outstanding_balance == invoice.due_amount`
on 100% of rows. That is the only money identity that holds.

## The join trap: `job.invoice_number` is the JOB number

`jobs.jsonl` has a field named `invoice_number`. **It is not the invoice's
number.** It is the job number — what Housecall Pro shows staff and what the
office says out loud. `invoices.jsonl` has its own `invoice_number` on a
separate sequence, in the same 4-digit range.

Joining on the number instead of the id fails silently and almost always:

| Join `jobs.invoice_number = invoices.invoice_number` | Rows |
|---|---|
| Jobs that match some invoice | 1,687 of 1,992 |
| ...that match an invoice belonging to a **different job** | **1,682** |
| ...that land on a **different customer's** invoice | **1,649** |
| ...that match correctly, by coincidence | **5** |

```
job_dd4866dec6  job.invoice_number='3520'  → real invoices: ['3717', '3695']
job_a8edd70d8b  job.invoice_number='3525'  → real invoices: ['3711']
job_cce3cfa376  job.invoice_number='158'   → real invoices: ['166']
```

**Rules.**

1. `job_id` is the **only** join key between jobs and invoices. Nothing else
   is permitted anywhere in the codebase.
2. **The name `invoice_number` does not exist on anything job-shaped, anywhere
   past the loader.** It survives only as a local variable inside the function
   that parses `jobs.jsonl`, which is the one place that has to speak the
   source's vocabulary. The moment a job leaves that function it carries
   `job_number` — in the SQLAlchemy model, the Pydantic schemas, every tool
   result, every API response, every row the web app renders.

   The `invoices` table keeps its own `invoice_number`, because that one is
   real. So the wrong join cannot be typed: there is no `job.invoice_number`
   on either side of an `==` to write it with. This is containment by naming,
   not a rule someone has to remember. `CLAUDE.md` hard rule 8 states the
   intent; T1.3's guard test enforces it.
3. **The agent speaks the job number to the caller**, because that is the
   number staff and customers use. Invoice numbers are for citing an invoice
   as evidence — a warranty line item, a balance — and must be labelled as
   such when spoken.
4. `notes.csv` also carries the job's `invoice_number` column. Same trap.

## Addresses

The dataset does not have a clean address key.

- 1,390 distinct `address.id` values, and 4 jobs where `address.id` is null
  while the address object itself is present and complete.
- **1,367** distinct `(street, street_line_2, city, state, zip)` tuples across
  the 1,390 rows of `customers[].addresses`, untouched — so 23 ids are a
  duplicate of a tuple another id already carries. This is the figure
  `scripts/verify_load.py` asserts, because it is a fact about the source
  rather than about a normalisation choice.
- The same count over **jobs** is 1,370, not 1,367: jobs include the 4 rows
  with no address id and one row of empty strings that the customer listing
  does not. Three different denominators, three different true numbers - name
  the denominator whenever quoting one.
- No address id ever carries two different streets. The reverse happens:
  **30 canonical addresses are split across 31 redundant address ids.**
- `street_line_2` is `null` on 1,171 jobs, the **empty string** on 267, and set
  on 554. Null and `""` are the same case and must normalise to the same value.
- `city` is noise. The anonymisation relocated cities inconsistently: zip
  33162 appears with 7 different city names, 33155 with 5. The same street and
  zip appears as both "Key Biscayne" and "Miami Beach". **City is not part of
  the key.**

**Canonical key** = normalised `street` + normalised `street_line_2` + `zip`,
where normalisation is strip + casefold and `null` and `""` collapse to the
same empty value. This yields **1,360 canonical addresses**, collapsing 30
groups that the raw address id splits. Including city and state in the key
instead yields 1,365 and only catches 25 of those groups — the 5 it misses are
the city-label collisions above, and they are genuine merges.

`address_alias(address_id → canonical_id)` is populated at load.
`resolve_address` returns `canonical_id`. `visit_history` is keyed on
`canonical_id`. See `docs/ARCHITECTURE.md`.

## Notes have no date

A note is exactly `{"id": ..., "content": ...}`. There is no timestamp, no
author, no type. Order within a job's `notes` array is roughly chronological
and is the only ordering signal that exists.

Therefore any date attached to a note is **the service date of the job the note
belongs to**, and must be spoken and rendered as such — "from the visit on
14 June", never "the note from 14 June". `search_notes` returns it under a
field named `job_service_date` so the distinction cannot be lost by accident.

## Work status distribution

`complete rated` 1004, `complete unrated` 633, `user canceled` 158,
`scheduled` 76, `pro canceled` 67, `needs scheduling` 40, `in progress` 14.

### Stale scheduled jobs

Of the 76 `scheduled` jobs, only **38 are in the future**. The other 38 are
dated 2026-03-07 to 2026-08-30, none has a `completed_at`, and 15 have some
partial work timestamp. They are abandoned rows, not work.

They are **stale**: excluded from the today view, excluded from availability
occupancy, and never spoken as an upcoming appointment. They surface only in
an explicit stale bucket on the operations dashboard. The rule and its
rationale are recorded in `docs/SCOPE.md`.

## Tags that matter

`Pipeline Automation` 735, `Campaigns` 217, **`ai-ready-for-review` 137**,
`Service Callback` 59, `Registration Needed` 56, `1 Yr Labor Warranty` 53,
`Warranty Claim` 46, `Registration Complete` 28, `Warranty Complete` 24,
`Install callback (service related)` 23, `Install callback (Part Failure)` 21,
`auto-voice` 6.

23 distinct tags in total; the remainder are low-count office tags including
the backslash-suffixed ones noted above.

`ai-ready-for-review` is the review queue this company already uses for
automated output. Async agent proposals are written with this tag.

## Warranty lives in three places and they disagree

1. **Job tags** — 118 jobs carry a warranty-related tag
   (`1 Yr Labor Warranty` 53, `Warranty Claim` 46, `Warranty Complete` 24).
2. **Invoice line items** — **64 items mention warranty case-insensitively.**
   61 match the exact prefix `WARRANTY Parts / Service - WARRANTY - <part>`.
   The other 3 do not:
   - `Compressor - UNDER WARRANTY`
   - `Unit Specific Parts - Defrost Control Board - Under Warranty`
   - `WARRANTY Unit Specific Parts - Outdoor Inverter Board & Indoor Control Board`

   The filter is therefore `name ILIKE '%warrant%'`, with the exact prefix as
   the parsed case and the other 3 handled as named exceptions. A
   `LIKE 'WARRANTY Parts / Service - WARRANTY - %'` filter silently loses 3
   covered parts, and a case-sensitive `'%WARRANTY%'` loses 1.
3. **Note prose** — 485 occurrences of "warranty" across **373 notes**.

There is **no install date and no warranty term field on the job.** Job keys
are: `address, assigned_employees, canceled_at, created_at, customer,
description, id, invoice_number, lead_source, notes, outstanding_balance,
schedule, tags, total_amount, updated_at, work_status, work_timestamps`.
Install date is derived — see below.

### Scope of a warranty answer

A warranty answer is scoped to **the canonical address plus the equipment the
caller named**. Not to a job. The caller asks about a compressor at a house;
the evidence for it is scattered across several jobs at that address. Resolve
the address first, then gather every warranty signal across all jobs at that
canonical address, then filter to the named equipment where the evidence names
equipment. If the caller named no equipment, answer at the address level and
say that is what you did.

### Derived install date

There is no install date in the source. It is derived: the job at the same
canonical address whose `description` identifies an installation, taking its
`work_timestamps.completed_at` as the install date. Where several qualify, the
most recent one before the job in question. Where none qualifies, level 3
below cannot fire and the answer falls through.

This derivation is its own build step — `docs/TASKS.md` T2.3a — because the
`1 Yr Labor Warranty` tag sits on the **install** job, not on the service job
the caller is phoning about.

### Precedence rule

Implement exactly this order. **Always return the basis with the answer.**

| # | Signal | Confidence | Answer |
|---|---|---|---|
| 1 | A note stating an explicit warranty term ("under warranty until 2030", a named term) | **high** | Covered per that term. Quote the note, attribute it to the tech, and give the **job's service date**. |
| 2 | An invoice line item matching `ILIKE '%warrant%'` | **high, historical** | This part *was* covered by the manufacturer on that visit. Cite the invoice number and its service date. Historical evidence of coverage, not proof of coverage today. |
| 3 | `1 Yr Labor Warranty` tag on the **derived install job** at this canonical address, with `completed_at` within 12 months | **high** | Labor covered. Cite the install job number and the install date. |
| 4 | `Warranty Claim` or `Registration Needed` on a job at this address | **medium** | A claim is open or registration is pending. Say what is in flight, do not assert an outcome, and **offer a human**. |
| 5 | `Warranty Complete` | **neutral** | Means the warranty *work was finished*, not that coverage ended. It is never evidence against coverage. It contributes context only; on its own it does not answer, and the answer falls to level 6. |
| 6 | Nothing | **unknown** | Not known. Offer to have someone check. |

Level 5 was previously written as "explicit `Warranty Complete` or expired term
→ not covered". That was semantically inverted. Reading all 24 tagged jobs, the
notes say things like "part is under warranty until 2030" — the tag records
completed warranty work. Treating it as a denial produced exactly the failure
`docs/HARNESS.md` Layer 2 exists to catch, in the direction that tells a
covered customer they are not covered.

Levels **4, 5 and 6** are spoken as uncertain and offered for human check. See
the refusal rules in `docs/AGENTS.md`.

## Frequent terms in notes

**These are occurrence counts, not note counts.** A term appearing three times
in one note counts three times. The note counts are given alongside because
eval coverage and STT keyterm weighting need different denominators.

| Term | Occurrences | Notes containing |
|---|---|---|
| `drain` | 1,470 | 848 |
| `not cooling` | 753 | 706 |
| `thermostat` | 735 | 472 |
| `condenser` | 649 | 467 |
| `compressor` | 575 | 354 |
| `warranty` | 485 | 373 |
| `capacitor` | 388 | 255 |
| `freon` | 166 | 135 |
| `r410` | 73 | 63 |

Useful as STT keyterm hints and as eval fixtures.
