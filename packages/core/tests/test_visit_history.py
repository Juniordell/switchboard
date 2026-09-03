"""`get_visit_history` against the live database."""

from switchboard_core.knowledge import VisitRow, get_visit_history

CANONICAL_ID = "cadr_7781ff2789ea56ff902b44968cfa1957"  # 103 Grouper Landing Rd


class TestOrderingAndShape:
    def test_most_recent_visit_is_first(self, db_session) -> None:
        visits = get_visit_history(db_session, CANONICAL_ID)
        assert len(visits) == 2
        assert visits[0].service_date > visits[1].service_date
        assert visits[0].job_id == "job_2a2366a26bad47b9ba6d1d04e4a779b1"
        assert visits[1].job_id == "job_dd4866dec6f44342b2f25bf506e4e9ff"

    def test_job_number_is_never_the_invoice_number(self, db_session) -> None:
        """The install visit's job_number is 3520; its two real invoices are
        3695 and 3717 - job_number must equal the former, never leak the
        latter, and the two must never collide.
        """
        visits = get_visit_history(db_session, CANONICAL_ID)
        install_visit = next(v for v in visits if v.job_id.startswith("job_dd4866"))
        assert install_visit.job_number == "3520"
        assert install_visit.job_number not in install_visit.invoice_numbers
        assert set(install_visit.invoice_numbers) == {"3695", "3717"}

    def test_multiple_invoices_on_one_job_are_all_present(self, db_session) -> None:
        visits = get_visit_history(db_session, CANONICAL_ID)
        install_visit = next(v for v in visits if v.job_id.startswith("job_dd4866"))
        assert len(install_visit.invoice_numbers) == 2

    def test_multiple_techs_on_one_job_are_all_present(self, db_session) -> None:
        visits = get_visit_history(db_session, CANONICAL_ID)
        install_visit = next(v for v in visits if v.job_id.startswith("job_dd4866"))
        assert len(install_visit.techs) == 4
        assert "Audrey Farrell" in install_visit.techs

    def test_unknown_canonical_id_returns_an_empty_list_not_an_error(
        self, db_session
    ) -> None:
        assert get_visit_history(db_session, "cadr_does_not_exist") == []


class TestNoGeneratedProse:
    """Every field is a fact traceable to a source column - there is nothing
    in the return type capable of holding a generated summary.
    """

    def test_the_row_type_carries_no_free_text_summary_field(self, db_session) -> None:
        assert set(VisitRow.model_fields) == {
            "job_id",
            "job_number",
            "service_date",
            "work_status",
            "description",
            "techs",
            "invoice_numbers",
            "outstanding_balance",
            "callback_from_job_id",
        }

    def test_description_is_the_source_field_verbatim(self, db_session) -> None:
        visits = get_visit_history(db_session, CANONICAL_ID)
        install_visit = next(v for v in visits if v.job_id.startswith("job_dd4866"))
        assert install_visit.description == "System Installation"


class TestCallbackLinking:
    """Full behavioural coverage lives in test_callback_chain.py; this
    confirms the field actually reaches a visit_history row.
    """

    def test_a_callback_visit_carries_its_source_job(self, db_session) -> None:
        visits = get_visit_history(db_session, "cadr_504bc35e11aa53a1a0aee8b6ebee6ad3")
        callback_visit = next(
            v for v in visits if v.job_id == "job_e90c888a7cba46468d1aec8ccc9d7022"
        )
        assert (
            callback_visit.callback_from_job_id
            == "job_27f927b643d0446d8b7c4caffd9b4f42"
        )

    def test_a_non_callback_visit_carries_none(self, db_session) -> None:
        visits = get_visit_history(db_session, CANONICAL_ID)
        assert all(v.callback_from_job_id is None for v in visits)
