"""T8.4: cases captured from real calls.

`docs/HARNESS.md`: every failure found by calling the agent becomes a
permanent case. These five come from five real inbound calls on the evening
of 2026-09-03, and each one records a defect those calls exposed that no
earlier test caught.

They are deliberately not conversation evals. Every assertion here is about
something that was wrong *underneath* the conversation - a normaliser that
added instead of concatenating, a request model that took the wrong kind of
id - so they need no model, cost nothing, and run on every commit. The
behaviour those defects produced is measured separately in
`test_conversations.py`.
"""

import datetime
from typing import ClassVar

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from switchboard_api.async_agents.reviewer import _open_promises, _writes
from switchboard_core.knowledge.address_normalize import normalize_street
from switchboard_core.knowledge.availability import DEFAULT_LIMIT
from switchboard_core.knowledge.resolve_address import resolve_address
from switchboard_core.knowledge.resolve_customer import resolve_customer
from switchboard_core.knowledge.warranty_status import (
    WarrantyCoverage,
    evaluate_warranty_status,
)
from switchboard_core.tools import (
    AvailabilityRequest,
    CustomerBalanceRequest,
    ToolError,
    VisitHistoryRequest,
    WarrantyStatusRequest,
    find_availability,
    get_warranty_status,
)

#: The harness's fixed clock, so a warranty verdict is reproducible.
AS_OF = datetime.datetime(2026, 9, 3, tzinfo=datetime.UTC)


class TestSpokenHouseNumbersConcatenate:
    """Golden case `spoken_number_grouping`. Call 1.

    The caller said "thirteen sixty three West Old Mangrove". The
    normaliser folded the whole run with one accumulator and returned
    **76** (13 + 63), so resolve_address offered three addresses on a
    different part of the street - 2441, 3092, 2421 - and the caller,
    reasonably, picked one. They were then read another property's visit
    history.

    People say house numbers in groups that concatenate. "eighty nine" is
    89 because a tens word absorbs a following unit; "thirteen sixty three"
    is 13 then 63.
    """

    @pytest.mark.parametrize(
        ("spoken", "expected"),
        [
            ("eighty nine", "89"),
            ("thirteen sixty three", "1363"),
            ("two ninety four", "294"),
            ("one hundred three", "103"),
            ("twelve fifty", "1250"),
            ("four", "4"),
        ],
    )
    def test_spoken_numbers(self, spoken: str, expected: str) -> None:
        assert normalize_street(spoken) == expected

    def test_the_t2_1_requirement_still_holds(self) -> None:
        """The case the whole normaliser was built for must not regress."""
        assert normalize_street("eighty nine harbor light shores") == (
            "89 harbor light shores"
        )

    def test_the_caller_now_reaches_their_own_street(self, db_session) -> None:
        result = resolve_address(
            db_session, "thirteen sixty three West Old Manios Road"
        )
        assert result.candidates
        assert all(c.display_address.startswith("1363") for c in result.candidates), [
            c.display_address for c in result.candidates
        ]
        # Several units share that number, so the agent still has to ask.
        assert result.must_ask is True


class TestAnIdOfTheWrongKindIsRefused:
    """Golden case `id_kind_refused`. Call 4.

    The agent called handoff_to_service with a **customer** id in the
    canonical_id slot. Nothing objected: the lookup found nothing and the
    caller was told there was no history.

    A wrong answer that looks like an empty one is the worst shape a bug
    can take here, so the prefixes are a type now.
    """

    #: A real customer - Tidewater Hospitality, 45 jobs - which is what
    #: made the original failure quiet: the id was valid, just not this
    #: kind of id.
    REAL_CUSTOMER_ID = "cus_0f7b6320d618477a973d44675b1a28a2"

    def test_a_customer_id_is_not_a_canonical_id(self) -> None:
        with pytest.raises(ValidationError, match="not a canonical id"):
            VisitHistoryRequest(canonical_id=self.REAL_CUSTOMER_ID)

    def test_the_misused_id_really_is_a_customer(self, db_session) -> None:
        """If this id ever stops being real, the case above stops being the
        bug it was captured from."""
        found = db_session.execute(
            text("SELECT company FROM source.customers WHERE id = :i"),
            {"i": self.REAL_CUSTOMER_ID},
        ).scalar_one()
        assert found == "Tidewater Hospitality"

    def test_a_canonical_id_is_not_a_customer_id(self) -> None:
        with pytest.raises(ValidationError, match="not a customer id"):
            CustomerBalanceRequest(customer_id="cadr_abc")

    def test_the_right_kind_still_passes(self) -> None:
        assert VisitHistoryRequest(canonical_id="cadr_abc").canonical_id == "cadr_abc"
        assert (
            WarrantyStatusRequest(
                canonical_id="cadr_abc", equipment="condenser"
            ).equipment
            == "condenser"
        )


class TestAHistoricalWarrantyIsNotAPresentOne:
    """Golden case `warranty_historical_tense`. Call 2.

    The caller asked whether a TXV was under warranty, and the agent said
    "Yes, the TXV is under warranty based on invoice 5275, which indicates
    it's manufacturer-covered" - present tense, from a 2023 invoice.

    `docs/AGENTS.md`: "Level 2 is stated as historical: the part *was*
    covered on that visit, which is not the same as covered today." The
    `basis` string said exactly that and was ignored, because the
    structured field next to it said `covered: "yes"`. Prose loses to a
    field. So the field carries the tense now.
    """

    #: 416 S Coral Ridge Pkwy (Lighthouse Warehouse). Invoice 4285 billed
    #: "WARRANTY Parts / Service - WARRANTY - Compressor"; no note, no
    #: install date, no tag. Level 2 and nothing else.
    CANONICAL_ID = "cadr_9323a56f80f958658708adf768c65dd3"

    def test_level_2_is_not_a_present_tense_yes(self, db_session) -> None:
        result = evaluate_warranty_status(db_session, self.CANONICAL_ID, as_of=AS_OF)
        assert result.level == 2
        assert result.covered is WarrantyCoverage.WAS_COVERED
        assert result.covered is not WarrantyCoverage.YES

    def test_the_value_reads_as_past_tense(self) -> None:
        """The agent sees this string. It has to be unmistakable on its own,
        without the basis beside it."""
        assert WarrantyCoverage.WAS_COVERED.value == "was_covered"

    def test_a_present_tense_yes_is_still_available_for_levels_1_and_3(
        self, db_session
    ) -> None:
        """Splitting the value must not have flattened everything into
        hedging: a current labor warranty still says yes."""
        result = evaluate_warranty_status(
            db_session, "cadr_7781ff2789ea56ff902b44968cfa1957", as_of=AS_OF
        )
        assert result.level == 3
        assert result.covered is WarrantyCoverage.YES


class TestGarbageInAnArgumentSlotFailsSafe:
    """Golden case `address_not_a_customer_name` grades the selection half
    of this at Layer 1; what follows is the half that matters. Call 3.

    The agent put an address in the customer-name slot -
    `resolve_customer(name="Bowline Isle Rd")` - and a house number in the
    equipment slot - `get_warranty_status(equipment="eighty")`.

    Both are the model misrouting an argument, and neither is worth a
    validator: "is this a person's name" is not a rule anyone can write
    honestly. What matters is which way they fail, and measured, both fail
    safe: the name scores 0.167 and returns must_ask, the equipment falls
    through to level 6 unknown. A wrong confident answer is the failure
    that hurts a caller; a question is not.

    These pin that direction, because the scoring thresholds are tunable
    and a future tweak could quietly turn 0.167 into a confident pick.
    """

    def test_an_address_in_the_name_slot_is_asked_about(self, db_session) -> None:
        result = resolve_customer(db_session, name="Bowline Isle Rd")
        assert result.must_ask is True
        assert result.candidates[0].score < 0.3

    def test_a_real_name_still_resolves(self, db_session) -> None:
        """The guard above must not be the scorer having become useless.
        The same call's real caller, misheard by STT, still lands."""
        result = resolve_customer(db_session, name="Stewart Fraser")
        assert result.must_ask is False
        assert result.candidates[0].display_name == "Stuart Fraser"

    def test_a_number_in_the_equipment_slot_answers_unknown(self, db_session) -> None:
        result = evaluate_warranty_status(
            db_session,
            "cadr_9323a56f80f958658708adf768c65dd3",
            equipment="eighty",
            as_of=AS_OF,
        )
        assert result.covered is WarrantyCoverage.UNKNOWN
        assert result.level == 6
        # Never "no". Not knowing is not a denial - docs/AGENTS.md.
        assert result.covered is not WarrantyCoverage.NO


class TestASpokenZeroIsAZero:
    """Golden case `spoken_zero_oh`. Captured from the production rehearsal
    on 2026-09-04.

    The caller said "eighty five oh four East Old Mangrove". People say
    "oh" for 0 inside a number, and `_ONES` knew only "zero", so the run
    was split and 8504 normalised to "85 oh 4" - scoring 0.714 against the
    right address instead of 1.0. The street name carried it that time. On
    a street with near neighbours it would not have.

    No vendor documents whether an STT emits "oh", "o" or "0" here, so the
    word is handled rather than assumed away.
    """

    @pytest.mark.parametrize(
        ("spoken", "expected"),
        [
            ("eighty five oh four", "8504"),
            ("eighty five zero four", "8504"),
            ("one oh three", "103"),
            ("oh", "oh"),
        ],
    )
    def test_oh_inside_a_number(self, spoken: str, expected: str) -> None:
        assert normalize_street(spoken) == expected

    def test_a_bare_oh_stays_a_word(self) -> None:
        """The guard that makes the rest safe. "oh" only counts once a
        numeric run is already open - otherwise an interjection would
        invent a house number."""
        assert normalize_street("oh and one more thing") == "oh and 1 more thing"
        assert normalize_street("oh hi there") == "oh hi there"

    def test_the_earlier_captured_cases_still_hold(self) -> None:
        """Adding "oh" must not disturb the grouping fixed for call 1."""
        assert normalize_street("thirteen sixty three") == "1363"
        assert normalize_street("eighty nine harbor light shores") == (
            "89 harbor light shores"
        )

    def test_the_rehearsal_address_resolves_exactly(self, db_session) -> None:
        result = resolve_address(
            db_session, "eighty five oh four east old mangrove road"
        )
        assert result.must_ask is False
        top = result.candidates[0]
        assert top.display_address.startswith("8504 E Old Mangrove Rd")
        # Was 0.714 while "oh" split the run; the point of the fix is that
        # a spoken zero costs nothing.
        assert top.score == pytest.approx(1.0)


class TestTheModelHasNoClock:
    """Captured from the production call of 2026-09-04 12:25. Asked to
    "schedule for next week", the model filled find_availability with the
    second week of October 2023 - its training data's idea of now - as
    naive datetimes. The aware/naive comparison raised TypeError, which
    T3.1 propagates as a defect; the model called it an internal error and
    transferred the caller.

    Two things hold now: a naive time is read as Miami rather than
    rejected, and a range in the past is a domain error that says which
    day today is, so the model can ask again with a real one.
    """

    AS_OF = datetime.datetime(2026, 9, 4, 15, 25, tzinfo=datetime.UTC)

    def test_a_past_range_names_today(self, db_session) -> None:
        """A domain error is a typed result, not an exception - T3.1's
        contract - so the assertion is on what the model gets handed."""
        out = find_availability(
            AvailabilityRequest(start="2023-10-09T08:00:00", end="2023-10-15T18:00:00"),
            call_id="probe",
            session=db_session,
            as_of=self.AS_OF,
        )
        assert isinstance(out, ToolError)
        assert "September 04, 2026" in out.model_dump_json()

    def test_a_naive_time_is_read_as_miami(self) -> None:
        request = AvailabilityRequest(
            start="2026-09-08T08:00:00", end="2026-09-08T18:00:00"
        )
        assert request.start.tzinfo is not None
        assert request.start.utcoffset() == datetime.timedelta(hours=-4)  # EDT

    def test_a_future_range_still_works(self, db_session) -> None:
        out = find_availability(
            AvailabilityRequest(start="2026-09-08T08:00:00", end="2026-09-12T18:00:00"),
            call_id="probe",
            session=db_session,
            as_of=self.AS_OF,
        )
        assert out.result_rows() > 0


class TestWarrantyEvidenceIsSpeakable:
    """Same call. The agent said the coverage was "associated with job
    number job_92c15112f0524b9f9ce428c420297fea" - the internal id, read
    out as if it were the number. Hard rule 8 is that the agent speaks the
    job number; the evidence now carries a `spoken` form and the prompt
    forbids anything that starts with an id prefix.
    """

    AS_OF = datetime.datetime(2026, 9, 3, tzinfo=datetime.UTC)

    @pytest.mark.parametrize(
        ("canonical_id", "level", "prefix"),
        [
            ("cadr_7781ff2789ea56ff902b44968cfa1957", 3, "job number "),
            ("cadr_9323a56f80f958658708adf768c65dd3", 2, "invoice "),
        ],
    )
    def test_spoken_is_a_number_never_an_id(
        self, db_session, canonical_id: str, level: int, prefix: str
    ) -> None:
        out = get_warranty_status(
            WarrantyStatusRequest(canonical_id=canonical_id),
            call_id="probe",
            session=db_session,
            as_of=self.AS_OF,
        )
        assert out.warranty.level == level
        spoken = out.warranty.evidence.spoken
        assert spoken.startswith(prefix), spoken
        for bad in ("job_", "cadr_", "cus_", "nte_"):
            assert bad not in spoken


class TestAKeptPromiseIsNotQueuedAsBroken:
    """Captured from the production call of 2026-09-04 15:50, the first
    that booked anything. The agent found times, the caller said
    "September seven 8 AM to 10 AM", `book_job` wrote the row and
    `ops.write_audit` recorded the words that authorised it - and the
    Reviewer filed it as "1 promise(s) with no write behind them".

    It was comparing the Extractor's `promised` list against its own
    `changed` list and never looking at what the agent actually did. A
    review queue that flags the calls that went right is a queue the
    office stops reading.
    """

    FACTS: ClassVar[dict[str, list[str]]] = {
        "promised": ["Your appointment has been scheduled for September 7th."],
        "changed": ["booked a visit"],  # phrased differently on purpose
    }

    def test_a_promise_with_an_audited_write_is_not_open(self) -> None:
        writes = [{"tool": "book_job", "spoken_confirmation": "September seven 8 AM"}]
        assert _open_promises(self.FACTS, writes) == []

    def test_a_promise_on_a_call_that_wrote_nothing_still_is(self) -> None:
        """The guard must not have turned the check off."""
        assert _open_promises(self.FACTS, []) == self.FACTS["promised"]

    def test_the_reviewer_is_handed_the_writes(self, db_session) -> None:
        """`_writes` reads the audit trail, not the transcript."""
        rows = _writes(db_session, "call_that_never_existed")
        assert rows == []


class TestSlotsAreOfferedNotListed:
    """Same call. `find_availability` returned ten slots and the agent read
    them aloud: 26.6 s of speaking, measured in Langfuse as the single
    longest thing on the call - longer than every LLM call in it together.

    The tool's own docstring says a caller is offered times, not a roster.
    Ten contradicted it.
    """

    def test_the_default_fits_a_phone_call(self) -> None:
        assert DEFAULT_LIMIT == 3

    def test_a_caller_who_wants_more_can_still_ask(self, db_session) -> None:
        out = find_availability(
            AvailabilityRequest(
                start="2026-09-08T08:00:00", end="2026-09-12T18:00:00", limit=8
            ),
            call_id="probe",
            session=db_session,
            as_of=datetime.datetime(2026, 9, 4, 15, 25, tzinfo=datetime.UTC),
        )
        assert out.result_rows() > 3
