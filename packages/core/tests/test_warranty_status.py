"""`evaluate_warranty_status`: the six-level precedence rule, against the
live database. Every fixture is real - found by querying `data/jobs.jsonl`
via the loaded database for a canonical address whose *only* warranty signal
is the level under test, so each test exercises exactly the branch it names.
"""

import datetime

from switchboard_core.knowledge import (
    WarrantyConfidence,
    WarrantyCoverage,
    evaluate_warranty_status,
)

AS_OF = datetime.datetime(2026, 9, 3, tzinfo=datetime.UTC)


class TestLevel1ExplicitNoteTerm:
    """1435 W Kelp Pointe Rd (cadr_2189f8c77d505f0a8d521f8f2d5e934a): a note
    reads "part is under warranty until 2030". The same job also carries two
    WARRANTY invoice line items and a Warranty Complete tag - level 1 must
    win over both anyway.
    """

    CANONICAL_ID = "cadr_2189f8c77d505f0a8d521f8f2d5e934a"

    def test_covered_yes_from_the_note(self, db_session) -> None:
        result = evaluate_warranty_status(db_session, self.CANONICAL_ID, as_of=AS_OF)
        assert result.covered is WarrantyCoverage.YES
        assert result.level == 1
        assert result.confidence is WarrantyConfidence.HIGH
        assert result.evidence.kind == "note"
        assert result.evidence.id == "nte_d3d1a4888626424ebe20f10fd24257f1"
        assert "under warranty until 2030" in result.basis

    def test_level_1_wins_over_level_2_and_level_5_on_the_same_job(
        self, db_session
    ) -> None:
        """The precedence order is not just "level 1 exists" - it has to
        beat real, present, competing evidence at levels 2 and 5 on this
        exact address, not an address where those levels are simply absent.
        """
        result = evaluate_warranty_status(db_session, self.CANONICAL_ID, as_of=AS_OF)
        assert result.level == 1
        assert result.evidence.kind != "invoice"


class TestLevel1ExplicitDenial:
    """10343 E Old Mangrove Rd, Building G unit 375
    (cadr_764a197e206b540493418b66d6ac482a): "...the unit is out of warranty
    and not worth having multiple part failures". The only level that can
    ever produce covered=no.
    """

    CANONICAL_ID = "cadr_764a197e206b540493418b66d6ac482a"

    def test_covered_no_from_the_note(self, db_session) -> None:
        result = evaluate_warranty_status(db_session, self.CANONICAL_ID, as_of=AS_OF)
        assert result.covered is WarrantyCoverage.NO
        assert result.level == 1
        assert result.confidence is WarrantyConfidence.HIGH
        assert result.evidence.kind == "note"
        assert result.evidence.id == "nte_c1e8ffa26bcb4ed28e2fe77aaab483b1"
        assert "out of warranty" in result.basis

    def test_the_conditional_note_on_the_same_job_is_not_what_won(
        self, db_session
    ) -> None:
        """The same job also has a note hedging "...if it is not under
        warranty it is low..." - a conditional about refrigerant charge, not
        an assertion. It must not be the evidence returned.
        """
        result = evaluate_warranty_status(db_session, self.CANONICAL_ID, as_of=AS_OF)
        assert result.evidence.id != "nte_fbfae0cf20864345b8204abf0a5ef69a"


class TestLevel2WarrantyLineItem:
    """416 S Coral Ridge Pkwy, Lighthouse Warehouse
    (cadr_9323a56f80f958658708adf768c65dd3): invoice 4285 billed
    "WARRANTY Parts / Service - WARRANTY - Compressor". No note, no install
    date, no tag at this address - level 2 alone.
    """

    CANONICAL_ID = "cadr_9323a56f80f958658708adf768c65dd3"

    def test_covered_yes_historical_from_the_invoice(self, db_session) -> None:
        result = evaluate_warranty_status(db_session, self.CANONICAL_ID, as_of=AS_OF)
        # Not YES. A real call turned a YES here into "it's under warranty",
        # present tense, from a 2023 invoice - see WarrantyCoverage.
        assert result.covered is WarrantyCoverage.WAS_COVERED
        assert result.level == 2
        assert result.confidence is WarrantyConfidence.HIGH_HISTORICAL
        assert result.evidence.kind == "invoice"
        assert result.evidence.id == "4285"
        assert "was covered" in result.basis
        assert "not proof of coverage today" in result.basis

    def test_scoped_to_the_named_equipment(self, db_session) -> None:
        result = evaluate_warranty_status(
            db_session, self.CANONICAL_ID, equipment="compressor", as_of=AS_OF
        )
        assert result.level == 2

    def test_a_different_named_equipment_finds_nothing_here(self, db_session) -> None:
        """The WARRANTY item is for a compressor. Asking about a thermostat
        at the same address must not borrow the compressor's evidence -
        falls all the way through to level 6.
        """
        result = evaluate_warranty_status(
            db_session, self.CANONICAL_ID, equipment="thermostat", as_of=AS_OF
        )
        assert result.covered is WarrantyCoverage.UNKNOWN
        assert result.level == 6


class TestLevel3RecentInstall:
    """103 Grouper Landing Rd (cadr_7781ff2789ea56ff902b44968cfa1957),
    installed 2026-03-02 - the T2.3a fixture. No note, no WARRANTY item, no
    tag at this address.
    """

    CANONICAL_ID = "cadr_7781ff2789ea56ff902b44968cfa1957"

    def test_covered_yes_from_the_derived_install_date(self, db_session) -> None:
        result = evaluate_warranty_status(db_session, self.CANONICAL_ID, as_of=AS_OF)
        assert result.covered is WarrantyCoverage.YES
        assert result.level == 3
        assert result.confidence is WarrantyConfidence.HIGH
        assert result.evidence.kind == "job"
        assert result.evidence.id == "job_dd4866dec6f44342b2f25bf506e4e9ff"

    def test_more_than_twelve_months_later_falls_through_to_unknown(
        self, db_session
    ) -> None:
        """Not a denial - evaluate_level_3 never produces one. Falls to
        level 6, same as no install date at all.
        """
        result = evaluate_warranty_status(
            db_session,
            self.CANONICAL_ID,
            as_of=datetime.datetime(2028, 6, 1, tzinfo=datetime.UTC),
        )
        assert result.covered is WarrantyCoverage.UNKNOWN
        assert result.covered is not WarrantyCoverage.NO
        assert result.level == 6


class TestLevel4ClaimOrRegistration:
    """320 Sandcastle Shores Dr (cadr_c2f1e65ac4c459d395d4883b34d977a0):
    the same job is both this address's install (level 3, 2026-04-25) *and*
    tagged Registration Needed (level 4) - a real, expected co-occurrence,
    since registering new equipment is what that tag means. `as_of` is set
    past the 12-month labor window so level 3 correctly steps aside and
    level 4 gets to fire.
    """

    CANONICAL_ID = "cadr_c2f1e65ac4c459d395d4883b34d977a0"
    PAST_LABOR_WARRANTY = datetime.datetime(2028, 1, 1, tzinfo=datetime.UTC)

    def test_level_3_fires_first_while_the_install_is_recent(self, db_session) -> None:
        result = evaluate_warranty_status(db_session, self.CANONICAL_ID, as_of=AS_OF)
        assert result.level == 3
        assert result.covered is WarrantyCoverage.YES

    def test_covered_unknown_from_the_tag_once_level_3_ages_out(
        self, db_session
    ) -> None:
        result = evaluate_warranty_status(
            db_session, self.CANONICAL_ID, as_of=self.PAST_LABOR_WARRANTY
        )
        assert result.covered is WarrantyCoverage.UNKNOWN
        assert result.level == 4
        assert result.confidence is WarrantyConfidence.MEDIUM
        assert result.evidence.kind == "job"
        assert result.evidence.id == "job_11d5abda001c4e30b4a70029e7d87b1a"
        assert "Registration Needed" in result.basis


class TestWarrantyCompleteIsNeverADenial:
    """The case this task explicitly requires: one of the 24 real
    Warranty Complete jobs, at an address with no other warranty signal at
    all (154 Leeward Key Cv, Unit 179 - cadr_613c03128b4c56339078f903adb33c41,
    exactly one job on record). If this tag were ever treated as a denial,
    this is the fixture that would prove it.
    """

    CANONICAL_ID = "cadr_613c03128b4c56339078f903adb33c41"
    WARRANTY_COMPLETE_JOB_ID = "job_c1bc25e00f204abaac4e67e0d9850c7c"

    def test_covered_is_unknown_never_no(self, db_session) -> None:
        result = evaluate_warranty_status(db_session, self.CANONICAL_ID, as_of=AS_OF)
        assert result.covered is WarrantyCoverage.UNKNOWN
        assert result.covered is not WarrantyCoverage.NO

    def test_falls_to_level_6_not_a_level_5_denial(self, db_session) -> None:
        """docs/DATA.md's level 5 never produces a verdict on its own, only
        context if the cascade reaches level 6 - `level` can never come back
        as 5 from this function, for any address.
        """
        result = evaluate_warranty_status(db_session, self.CANONICAL_ID, as_of=AS_OF)
        assert result.level == 6
        assert result.level != 5

    def test_the_tag_is_surfaced_as_context_not_hidden(self, db_session) -> None:
        result = evaluate_warranty_status(db_session, self.CANONICAL_ID, as_of=AS_OF)
        assert result.evidence.kind == "job"
        assert result.evidence.id == self.WARRANTY_COMPLETE_JOB_ID
        assert "Warranty Complete" in result.basis

    def test_the_basis_explains_what_the_tag_means_not_a_denial(
        self, db_session
    ) -> None:
        result = evaluate_warranty_status(db_session, self.CANONICAL_ID, as_of=AS_OF)
        assert "finished" in result.basis
        assert "not that coverage has ended" in result.basis
        assert "not covered" not in result.basis
        assert "no coverage" not in result.basis


class TestLevel6Nothing:
    """130 Seahorse Pointe St (cadr_40a6e7df63c252b490e690c91f70c999): three
    real jobs, two completed - genuine service history - and zero warranty
    signal anywhere. Not an address nobody ever called about; one that was
    serviced and simply has nothing to report.
    """

    CANONICAL_ID = "cadr_40a6e7df63c252b490e690c91f70c999"

    def test_covered_unknown_with_no_evidence(self, db_session) -> None:
        result = evaluate_warranty_status(db_session, self.CANONICAL_ID, as_of=AS_OF)
        assert result.covered is WarrantyCoverage.UNKNOWN
        assert result.level == 6
        assert result.confidence is WarrantyConfidence.UNKNOWN
        assert result.evidence is None
        assert result.basis == "not known. Offer to have someone check."


class TestStructuralGuarantees:
    def test_never_a_bare_boolean(self, db_session) -> None:
        """The whole point of the return contract: covered is a three-state
        enum a caller cannot mistake for Python's bool, basis is always a
        non-empty string, and confidence is always present.
        """
        result = evaluate_warranty_status(
            db_session, "cadr_40a6e7df63c252b490e690c91f70c999", as_of=AS_OF
        )
        assert not isinstance(result.covered, bool)
        assert result.covered in {
            WarrantyCoverage.YES,
            WarrantyCoverage.WAS_COVERED,
            WarrantyCoverage.NO,
            WarrantyCoverage.UNKNOWN,
        }
        assert result.basis
        assert result.confidence is not None

    def test_level_is_always_one_of_the_six(self, db_session) -> None:
        for canonical_id in (
            "cadr_2189f8c77d505f0a8d521f8f2d5e934a",
            "cadr_9323a56f80f958658708adf768c65dd3",
            "cadr_7781ff2789ea56ff902b44968cfa1957",
            "cadr_613c03128b4c56339078f903adb33c41",
            "cadr_40a6e7df63c252b490e690c91f70c999",
        ):
            result = evaluate_warranty_status(db_session, canonical_id, as_of=AS_OF)
            assert result.level in {1, 2, 3, 4, 5, 6}
