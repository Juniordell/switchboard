# The dataset

Six months of one HVAC company's records, exported from Housecall Pro.
March–September 2026. Names, addresses and amounts are anonymised consistently.
`[phone]`, `[email]`, `[code]` are redaction markers, not values.

## Measured shape

| Fact | Value |
|---|---|
| Jobs | 1,992 |
| Notes | 6,954 (median 120 chars, p95 801, max 10,076) |
| Total note text | ~1.5 MB |
| Invoices / line items | 1,700 / 4,390 |
| Customers | 732 (1,638 jobs homeowner, 354 business) |
| Distinct addresses | 1,188 (414 seen more than once, 1.7 jobs per address) |
| Employees | 23 |
| Scheduled after 2026-09-02 | 42 (last: 2026-09-15) |

Money is in **cents** in the `.jsonl` files and dollars in the `.csv` mirrors.
Load from `.jsonl`.

## Work status distribution

`complete rated` 1004, `complete unrated` 633, `user canceled` 158,
`scheduled` 76, `pro canceled` 67, `needs scheduling` 40, `in progress` 14.

## Tags that matter

`Pipeline Automation` 735, `Campaigns` 217, **`ai-ready-for-review` 137**,
`Service Callback` 59, `Registration Needed` 56, `1 Yr Labor Warranty` 53,
`Warranty Claim` 46, `Registration Complete` 28, `Warranty Complete` 24,
`Install callback (service related)` 23, `Install callback (Part Failure)` 21,
`auto-voice` 6.

`ai-ready-for-review` is the review queue this company already uses for
automated output. Async agent proposals are written with this tag.

## Warranty lives in three places and they disagree

1. **Job tags** — 118 jobs carry a warranty-related tag.
2. **Invoice line items** — 64 items named `WARRANTY Parts / Service - WARRANTY - <part>`.
3. **Note prose** — 485 mentions of "warranty" typed by hand.

Plus install date + term for labor warranty, which lives on the job.

**Precedence rule** (implement exactly this, and return the basis with the answer):

1. An explicit `Warranty Complete` or expired term → not covered, with the date.
2. An invoice `WARRANTY` line item → part covered by manufacturer, cite invoice number.
3. `1 Yr Labor Warranty` tag + install date within 12 months → labor covered, cite the install job.
4. Note prose mentioning a warranty term → **low confidence**, quote the note and say it is from a tech's note.
5. Nothing → not known, offer to have someone check.

## Frequent terms in notes

`drain` 1470, `not cooling` 753, `thermostat` 735, `condenser` 649,
`compressor` 575, `warranty` 485, `capacitor` 388, `freon` 166, `r410` 73.
Useful as STT keyterm hints and as eval fixtures.