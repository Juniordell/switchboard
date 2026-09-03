"""Pure normalisation functions. No database - these run anywhere, fast."""

import pytest

from switchboard_core.knowledge.address_normalize import (
    DIRECTIONAL_TOKEN_ABBREVIATIONS,
    STREET_TOKEN_ABBREVIATIONS,
    canonical_address_key,
    normalize_street,
    normalize_unit,
    normalize_zip,
)


@pytest.mark.parametrize(
    ("spoken", "digits"),
    [
        ("eighty nine harbor light shores", "89 harbor light shores"),
        ("eighty-nine harbor light shores", "89 harbor light shores"),
        ("twenty leeward pointe", "20 leeward pointe"),
        ("one hundred four grouper hollow square", "104 grouper hollow sq"),
        ("ten thousand three hundred forty three", "10343"),
        ("nine hundred old mangrove", "900 old mangrove"),
    ],
)
def test_number_words_convert_to_digits(spoken: str, digits: str) -> None:
    assert normalize_street(spoken) == digits


@pytest.mark.parametrize(
    ("raw", "expected_token"),
    [
        ("89 Harborlight Shores Boulevard", "blvd"),
        ("89 Harborlight Shores Road", "rd"),
        ("89 Harborlight Shores Drive", "dr"),
        ("89 Harborlight Shores Lane", "ln"),
        ("89 Harborlight Shores Way", "wy"),
        ("89 Harborlight Shores Cove", "cv"),
        ("89 Harborlight Shores West", "w"),
        ("89 Harborlight Shores North", "n"),
    ],
)
def test_full_word_suffixes_and_directions_abbreviate(
    raw: str, expected_token: str
) -> None:
    assert normalize_street(raw).split()[-1] == expected_token


def test_abbreviations_pass_through_unchanged() -> None:
    """The already-abbreviated form is a fixed point of the function."""
    assert normalize_street("89 Harborlight Shores Blvd W") == normalize_street(
        normalize_street("89 Harborlight Shores Blvd W")
    )


def test_every_abbreviation_table_entry_round_trips() -> None:
    for full, short in {
        **STREET_TOKEN_ABBREVIATIONS,
        **DIRECTIONAL_TOKEN_ABBREVIATIONS,
    }.items():
        assert normalize_street(full) == short
        assert normalize_street(short) == short


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("89 Harborlight Shores Blvd W", "  89   HARBORLIGHT   shores   BLVD   w  "),
        ("85 S Banyan Key Ln", "85 South Banyan Key Lane"),
        ("1615 S Coral Ridge Pkwy", "1615 South Coral Ridge Parkway"),
    ],
)
def test_case_and_whitespace_collapse(a: str, b: str) -> None:
    assert normalize_street(a) == normalize_street(b)


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_normalize_street_on_nothing_is_empty(empty: str | None) -> None:
    assert normalize_street(empty) == ""


@pytest.mark.parametrize("empty", [None, ""])
def test_normalize_unit_collapses_null_and_empty(empty: str | None) -> None:
    assert normalize_unit(empty) == ""


def test_normalize_unit_is_case_insensitive() -> None:
    assert normalize_unit("Unit 202") == normalize_unit("unit 202") == "unit 202"


def test_normalize_zip_passes_through() -> None:
    assert normalize_zip("33162") == "33162"
    assert normalize_zip(None) == ""


class TestCanonicalAddressKey:
    def test_empty_street_has_no_key(self) -> None:
        assert canonical_address_key("", "", None) is None
        assert canonical_address_key(None, None, None) is None
        assert canonical_address_key("   ", "unit 5", "33162") is None

    def test_null_and_empty_unit_produce_the_same_key(self) -> None:
        a = canonical_address_key("20 Leeward Pointe", "", "33182")
        b = canonical_address_key("20 Leeward Pointe", None, "33182")
        assert a == b
        assert a.canonical_id() == b.canonical_id()

    def test_the_real_duplicate_id_pair_shares_a_canonical_key(self) -> None:
        """adr_fa92f98435... and adr_150af82d85... - real ids, same address,
        differing only in the anonymiser's inconsistent city label (excluded
        from the key) - see docs/DATA.md.
        """
        a = canonical_address_key("20 Leeward Pointe", "", "33182")
        b = canonical_address_key("20 Leeward Pointe", None, "33182")
        assert a.canonical_id() == b.canonical_id()

    def test_canonical_id_is_deterministic_across_calls(self) -> None:
        key1 = canonical_address_key("89 Harborlight Shores Blvd W", None, "33162")
        key2 = canonical_address_key("89 Harborlight Shores Blvd W", None, "33162")
        assert key1.canonical_id() == key2.canonical_id()

    def test_canonical_id_changes_with_the_key(self) -> None:
        a = canonical_address_key("89 Harborlight Shores Blvd W", None, "33162")
        b = canonical_address_key("4 Harborlight Shores Blvd S", None, "33162")
        assert a.canonical_id() != b.canonical_id()

    def test_city_and_state_are_not_part_of_the_key(self) -> None:
        """The anonymiser relocated cities inconsistently - zip 33162 alone
        carries 7 different city labels for what is otherwise the same
        street. City must never affect the key.
        """
        # canonical_address_key doesn't take city/state at all - the
        # signature itself is the guarantee. This test documents why.
        import inspect

        params = inspect.signature(canonical_address_key).parameters
        assert set(params) == {"street", "unit", "zip_code"}
