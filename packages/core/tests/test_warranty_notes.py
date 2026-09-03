"""Level 1's lexical classifier. No database - pure text in, claim out."""

import pytest

from switchboard_core.knowledge import NoteWarrantyClaim, classify_note_warranty_term


@pytest.mark.parametrize(
    "content",
    [
        "part is under warranty until 2030 \nincludes $96 warranty fee",
        "Unit is under warranty until 6/2026\nMingle for parts",
        "still under warranty, in stock ($1193)",
        "he is covered under warranty, sent estimates for review",
        "under warranty until 2028",
    ],
)
def test_positive_phrases_classify_as_covered(content: str) -> None:
    assert classify_note_warranty_term(content) is NoteWarrantyClaim.COVERED


@pytest.mark.parametrize(
    "content",
    [
        "First floor needs a new fan motor unit is out of warranty",
        "No longer under warranty\nMingle\nJasmine take 2-4 days",
        "Warranty status expired (out of warranty)",
        "Both units are not under warranty- never registered",
        "Gemaire: warranty expired (standard 5-year)",
        "spoke to Pace, we are not quoting a repair option since the unit "
        "is out of warranty and not worth having multiple part failures",
    ],
)
def test_negative_phrases_classify_as_not_covered(content: str) -> None:
    assert classify_note_warranty_term(content) is NoteWarrantyClaim.NOT_COVERED


def test_notes_with_no_explicit_term_classify_as_none() -> None:
    assert classify_note_warranty_term("Cleared the drain line, tested system") is None
    assert (
        classify_note_warranty_term("Replaced capacitor, unit cooling normally") is None
    )


class TestConditionalHedgeIsNotAClaim:
    """The bug found by running the real level-1-negative fixture end to end:
    "...if it is not under warranty it is low..." is a hedge about something
    else (refrigerant charge), not an assertion of the unit's status, but a
    naive substring check on "not under warranty" fires on it anyway.
    """

    REAL_HEDGE = (
        "Has small leak on indoor needs replacement mini split it is closed "
        "to 5 years old recommend replacing to get a warranty if it is not "
        "under warranty it is low maybe 1 pound needs new disconnect box"
    )

    def test_the_real_note_that_exposed_the_bug(self) -> None:
        assert classify_note_warranty_term(self.REAL_HEDGE) is None

    @pytest.mark.parametrize(
        "content",
        [
            "it would be ideal to change out the compressor if the unit's "
            "under warranty or change out the whole system",
            "If the system is not under warranty, what would mean changing "
            "out the entire system due to the extreme cost of a compressor",
            "Even if the system is under warranty the whole condenser will "
            "need be replaced",
            "iF, the system is not under warranty. I recommend replacing "
            "the whole system",
            "We will need to check and see if it's under warranty and "
            "exchange it as soon as possible",
            "Budget for replacement or repair if system is under warranty "
            "as the compressor is likely on its way out",
        ],
    )
    def test_every_real_hedge_found_in_the_corpus(self, content: str) -> None:
        """All six read in full from data/jobs.jsonl while investigating the
        bug - genuinely conditional, none contains an unconditional
        assertion elsewhere in the same note.
        """
        assert classify_note_warranty_term(content) is None

    def test_an_unconditional_claim_still_works_even_with_if_elsewhere(self) -> None:
        """The fix must not become "suppress on any 'if' near 'warranty'" -
        it targets the specific "if ... under warranty" construction.
        """
        content = (
            "If the customer calls back, tell them the compressor "
            "is still under warranty until 2028."
        )
        # "If" appears, but not immediately governing "under warranty" -
        # more than 30 characters separate them here.
        assert classify_note_warranty_term(content) is NoteWarrantyClaim.COVERED
