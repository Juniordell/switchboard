"""Level 1 of the warranty precedence rule: an explicit warranty term typed
by a tech, in a note.

Lexical, not statistical - a fixed set of phrases checked against the note
verbatim, chosen from what actually appears in `data/jobs.jsonl`'s notes, the
same way `docs/DATA.md`'s address-suffix table was: counted, not guessed.
Negative phrases are checked first, since some are more specific supersets a
looser positive check would otherwise catch first (a positive rule that just
looked for the substring "under warranty" would also fire on "**not** under
warranty").

**This module does not re-verify a claimed date.** "Under warranty until
2030" is trusted and quoted, not parsed into a year and compared against
`as_of` - the ten real "until <date>" notes in this dataset are all dated
consistently (the claimed date is always after the note's own job date), and
inventing date parsing for free-form tech shorthand ("6/2026", "28",
"2030") risks getting a real claim wrong in a way a verbatim quote cannot.
Matches how `docs/DATA.md`'s level 1 already reads: "Quote the note,
attribute it to the tech" - not "and confirm the date still holds."

**Conditional phrasing is not a claim.** A real note reads: "...recommend
replacing to get a warranty **if it is not under warranty** it is low maybe 1
pound...". Read straight, `\bnot under warranty\b` fires on this - but the
tech is hedging about something else (refrigerant charge) in passing, not
asserting the unit's status either way. `_CONDITIONAL_HEDGE` is checked first
and suppresses a match entirely rather than trying to classify a conditional
as a positive or negative claim. Found by running the real level-1-negative
fixture end to end and getting the wrong note back, not by inspection -
`nte_fbfae0cf...` on the same job as the genuine "out of warranty" note
`nte_c1e8ffa2...`, tied on `job_date` and winning the tie only because of
Postgres row order.
"""

import re
from enum import StrEnum

#: "if ... under warranty" within a short span - a hedge about what to do
#: depending on a status not yet known, not an assertion of that status.
_CONDITIONAL_HEDGE = re.compile(r"\bif\b.{0,30}\bunder warranty\b", re.IGNORECASE)

_NEGATIVE_PATTERNS = (
    re.compile(r"\bnot under warranty\b", re.IGNORECASE),
    re.compile(r"\bno longer\b.{0,25}\bwarranty\b", re.IGNORECASE),
    re.compile(r"\bout of warranty\b", re.IGNORECASE),
    re.compile(r"\bwarranty\b.{0,10}\bexpired\b", re.IGNORECASE),
)

_POSITIVE_PATTERNS = (
    re.compile(r"\bstill under warranty\b", re.IGNORECASE),
    re.compile(r"\bunder warranty until\b", re.IGNORECASE),
    re.compile(r"\bwarranty until\b", re.IGNORECASE),
    re.compile(r"\bcovered under warranty\b", re.IGNORECASE),
)


class NoteWarrantyClaim(StrEnum):
    COVERED = "covered"
    NOT_COVERED = "not_covered"


def classify_note_warranty_term(content: str) -> NoteWarrantyClaim | None:
    """Read one note for an explicit warranty claim. `None` means the note
    says nothing explicit either way - not a signal, silence - which is also
    what a conditional hedge produces, deliberately.
    """
    if _CONDITIONAL_HEDGE.search(content):
        return None
    for pattern in _NEGATIVE_PATTERNS:
        if pattern.search(content):
            return NoteWarrantyClaim.NOT_COVERED
    for pattern in _POSITIVE_PATTERNS:
        if pattern.search(content):
            return NoteWarrantyClaim.COVERED
    return None
