"""Normalising a street address into a canonical key.

The source has no address entity. 1,390 `address.id` values, minted per
customer-address occurrence, cover only **1,359** physically distinct
addresses once normalised — 30 of them split across 31 redundant ids for no
reason a caller would recognise: a stray casing difference in a unit number,
or the same street relocated to a different fictional city label by the
anonymiser. Chaining history off `address.id` silently tells half a story.
See `docs/DATA.md`.

**Canonical key** = normalised `street` + normalised `street_line_2` +
`zip`. `city` and `state` are deliberately excluded: the anonymiser relocated
cities inconsistently (zip 33162 alone carries 7 different city labels for
what is otherwise the same street), so including them would under-merge
addresses that are the same place.

Normalisation has two jobs, and they are different jobs:

1. **Collapse what should never have been distinct** — case, whitespace,
   `null` vs `""` on the unit, and the abbreviation-vs-spelled-out variance
   this specific dataset actually contains (`Rd`/`Road`, `Wy`/`Way`,
   `Cv`/`Cove`, `N`/`North`, ...; see :data:`STREET_TOKEN_ABBREVIATIONS`). This
   applies identically to a stored address and to a caller's spoken query,
   because it is the same function.
2. **Convert a spoken number into digits** (`"eighty nine"` → `"89"`,
   `"thirteen sixty three"` → `"1363"` - groups concatenate, they do not
   add), which
   only a caller's transcribed speech ever needs, since every stored house
   number in the source is already a digit.

What normalisation does **not** do is bridge two words into one
(`"harbor light"` vs `"Harborlight"`). That gap is what `pg_trgm` similarity
is for — trigram overlap survives a word-boundary difference; a normaliser
built to also swallow it would have to know every fictional street-name
compound in the dataset. Confirmed against the real address the hard
requirement below names: `similarity('89 harbor light shores',
'89 harborlight shores blvd w')` is 0.405 before number-word conversion and
0.625 after — the conversion is what clears the 0.55 threshold, not
guesswork.
"""

import re
import uuid
from dataclasses import dataclass

#: Fixed forever. Every canonical_id is uuid5(NAMESPACE, key); changing this
#: constant would silently reassign every canonical_id on the next load.
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "switchboard.knowledge.canonical_address")

#: The field separator used inside the key fed to uuid5. 0x1F (ASCII unit
#: separator) cannot appear in normal address text, so it cannot be forged by
#: a street or unit value that happens to contain the "real" delimiter.
_KEY_SEP = "\x1f"

# ---------------------------------------------------------------------------
# Token abbreviations: spelled-out form -> abbreviation. The abbreviated form
# was chosen as the canonical direction because the caller's utterance is
# almost always TRUNCATED, not just abbreviated - "eighty nine harbor light
# shores" says
# neither "boulevard" nor "west" at all, it just stops. A shorter canonical
# target dilutes less against a short query: measured directly,
# similarity('89 harbor light shores', '<street> blvd w') is 0.625, while the
# same query against the fully spelled-out '<street> boulevard west' is only
# 0.5 - below CONFIDENCE_THRESHOLD, because the extra trigrams from the two
# spelled-out words that were never said count against the match. Abbreviating
# also cuts false confidence the other way: a generic query like "reef drive"
# scores 0.46 against an unrelated "...Reef Drive" address normalised in full,
# but only 0.28 normalised to "...reef dr". Shorter is better on both sides of
# this tradeoff, not a wash - see docs/DECISIONS.md.
#
# Every entry below was checked against data/customers.jsonl: counted how
# often each token appears as a whole word across all 1,390 addresses, and
# kept only what actually occurs. This is a fit to this dataset's fictional
# street generator, not a general USPS abbreviation table - "St" as "Saint"
# is not handled, because it never appears in this data.
# ---------------------------------------------------------------------------

STREET_TOKEN_ABBREVIATIONS: dict[str, str] = {
    # Standard USPS-style suffixes, both forms seen in the data.
    "street": "st",
    "road": "rd",
    "drive": "dr",
    "lane": "ln",
    "boulevard": "blvd",
    "avenue": "ave",
    "court": "ct",
    "place": "pl",
    "circle": "cir",
    "parkway": "pkwy",
    "square": "sq",
    "terrace": "ter",
    "trail": "trl",
    "highway": "hwy",
    "expressway": "expy",
    "alley": "aly",
    # Non-standard abbreviations this dataset's generator actually uses.
    "way": "wy",
    "cove": "cv",
}

DIRECTIONAL_TOKEN_ABBREVIATIONS: dict[str, str] = {
    "north": "n",
    "south": "s",
    "east": "e",
    "west": "w",
    "northeast": "ne",
    "northwest": "nw",
    "southeast": "se",
    "southwest": "sw",
}

_ALL_TOKEN_ABBREVIATIONS = {
    **STREET_TOKEN_ABBREVIATIONS,
    **DIRECTIONAL_TOKEN_ABBREVIATIONS,
}

# ---------------------------------------------------------------------------
# English number words -> digits, for a caller's spoken house number. Stored
# addresses never need this leg: every house number in the source is already
# numeric.
# ---------------------------------------------------------------------------

#: "oh" is how people say 0 inside a number - "eighty five oh four" is
#: 8504. No vendor documents whether an STT emits "oh", "o" or "0" here,
#: so this handles the word defensively rather than trusting the model.
#:
#: It is deliberately NOT in `_NUMBER_WORDS`: on its own, "oh" is an
#: interjection ("oh, and one more thing"), and turning that into a 0
#: would invent a house number out of a filler word. It only counts when
#: it lands inside a run that is already numeric - see `_number_groups`.
_OH = "oh"

_ONES = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
}
_TEENS = {
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_MULTIPLIERS = {"hundred": 100, "thousand": 1000}
_NUMBER_WORDS = (
    frozenset(_ONES) | frozenset(_TEENS) | frozenset(_TENS) | frozenset(_MULTIPLIERS)
)

_WHITESPACE = re.compile(r"\s+")


def _words_to_number(words: list[str]) -> int:
    """Fold one *group* of English cardinal-number words into an integer.

    Standard accumulate-and-carry: "hundred" scales the value collected so
    far, "thousand" flushes it. This handles a single group - "eighty nine"
    is 89, "one hundred three" is 103. Splitting a spoken house number into
    groups is `_number_groups`' job, and the two must not be confused.
    """
    if words == [_OH]:
        return 0

    total = 0
    current = 0
    for word in words:
        if word in _ONES:
            current += _ONES[word]
        elif word in _TEENS:
            current += _TEENS[word]
        elif word in _TENS:
            current += _TENS[word]
        elif word == "hundred":
            current = (current or 1) * 100
        elif word == "thousand":
            total += (current or 1) * 1000
            current = 0
    return total + current


def _number_groups(words: list[str]) -> list[list[str]]:
    """Split a run of number words the way a person says a house number.

    People read house numbers in **groups**, and the groups concatenate
    rather than add: "thirteen sixty three" is 13 then 63, meaning 1363,
    not 13 + 63. Folding the whole run with one accumulator returns 76, and
    a caller at 1363 W Old Mangrove was offered three addresses on another
    street - found on a real call, not in a test.

    "eighty nine" stays one group because a tens word can absorb a
    following unit, which is the pattern the T2.1 requirement rests on. A
    new group starts wherever the next word cannot be absorbed: a teen or a
    ten after a group that already has a value, or a unit after a unit.
    """
    groups: list[list[str]] = []
    current: list[str] = []
    absorbing = False  # the group ends in a tens word and can take a unit

    for word in words:
        if word == _OH:
            # A spoken zero. Its own group, so "eighty five oh four"
            # concatenates to 85|0|4 = 8504 instead of being folded into a
            # neighbour's arithmetic.
            if current:
                groups.append(current)
            groups.append([_OH])
            current = []
            absorbing = False
            continue
        if word in _MULTIPLIERS:
            current.append(word)
            absorbing = False
            continue
        if not current:
            current.append(word)
            absorbing = word in _TENS
            continue
        if absorbing and word in _ONES:
            current.append(word)
            absorbing = False
            continue
        if "hundred" in current or "thousand" in current:
            # "one hundred three" is still one number.
            current.append(word)
            absorbing = word in _TENS
            continue
        groups.append(current)
        current = [word]
        absorbing = word in _TENS

    if current:
        groups.append(current)
    return groups


def _convert_number_word_runs(tokens: list[str]) -> list[str]:
    """Replace every maximal run of number words with its digit form."""
    out: list[str] = []
    run: list[str] = []

    def flush() -> None:
        if run:
            # Groups concatenate: "thirteen sixty three" -> "13" + "63".
            out.append("".join(str(_words_to_number(g)) for g in _number_groups(run)))
            run.clear()

    for token in tokens:
        if token in _NUMBER_WORDS:
            run.append(token)
        elif token == _OH and run:
            # A spoken zero, but only mid-run. `run` being non-empty is the
            # whole guard: "eighty five oh four" is a house number, while a
            # bare "oh" that starts a phrase is someone thinking out loud
            # and must stay a word.
            run.append(token)
        else:
            flush()
            out.append(token)
    flush()
    return out


def normalize_street(text: str | None) -> str:
    """Canonicalise a street string: case, whitespace, tokens, spoken numbers.

    Applied identically to a stored address and to a caller's spoken query -
    that symmetry is the entire point. Hyphens are treated as word breaks
    ("eighty-nine" tokenises the same as "eighty nine"), which costs nothing
    for this dataset's addresses since none contain a hyphenated street name.
    """
    if not text:
        return ""
    lowered = text.strip().lower().replace("-", " ")
    tokens = _WHITESPACE.split(lowered) if lowered else []
    tokens = [t for t in tokens if t]
    tokens = _convert_number_word_runs(tokens)
    tokens = [_ALL_TOKEN_ABBREVIATIONS.get(t, t) for t in tokens]
    return " ".join(tokens)


def normalize_unit(text: str | None) -> str:
    """Canonicalise a unit/suite value. `None` and `""` collapse to `""`."""
    if not text:
        return ""
    return _WHITESPACE.sub(" ", text.strip().lower())


def normalize_zip(text: str | None) -> str:
    """Canonicalise a zip. No token expansion; zips are already clean."""
    return text.strip() if text else ""


@dataclass(frozen=True)
class CanonicalKey:
    street: str
    unit: str
    zip: str

    def as_string(self) -> str:
        return f"{self.street}{_KEY_SEP}{self.unit}{_KEY_SEP}{self.zip}"

    def canonical_id(self) -> str:
        return f"cadr_{uuid.uuid5(NAMESPACE, self.as_string()).hex}"


def canonical_address_key(
    street: str | None, unit: str | None, zip_code: str | None
) -> CanonicalKey | None:
    """Build the canonical key, or `None` if there is no address to key.

    Returns `None` when the normalised street is empty. One row in
    `customers.jsonl` (`adr_c6efbfa7...`) has every address field blank; without
    this guard its empty key would coincidentally equal the key of any other
    fully-blank address - including a job whose entire `address` object is
    `null`, which normalises to the same empty triple. An empty street is "no
    known address," never a match.
    """
    street_norm = normalize_street(street)
    if not street_norm:
        return None
    return CanonicalKey(street_norm, normalize_unit(unit), normalize_zip(zip_code))
