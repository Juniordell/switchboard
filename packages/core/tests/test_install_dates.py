"""`knowledge.install_dates` against the live, loaded database."""

from sqlalchemy import text

from switchboard_core.knowledge import INSTALL_DESCRIPTION_PREFIXES


def test_the_prefix_list_is_exactly_what_was_validated() -> None:
    """Median invoice $10k-27k against $456 for an ordinary repair, plus
    Registration Needed/Complete tags on the matched jobs - see
    build_install_dates.py's module docstring for the full validation.
    """
    assert INSTALL_DESCRIPTION_PREFIXES == (
        "System Installation",
        "New System Installation",
        "New Construction",
    )


def test_exactly_62_canonical_addresses_have_an_install_date(db_session) -> None:
    count = db_session.execute(
        text("SELECT count(*) FROM knowledge.install_dates")
    ).scalar_one()
    assert count == 62


def test_a_known_install_resolves_to_its_job_and_date(db_session) -> None:
    """job_dd4866dec6... is "System Installation" at 103 Grouper Landing Rd,
    completed 2026-03-02T22:13:00Z.
    """
    row = db_session.execute(
        text(
            "SELECT id.canonical_id, id.install_date, ca.display_street "
            "FROM knowledge.install_dates id "
            "JOIN knowledge.canonical_addresses ca "
            "  ON ca.canonical_id = id.canonical_id "
            "WHERE id.install_job_id = 'job_dd4866dec6f44342b2f25bf506e4e9ff'"
        )
    ).first()
    assert row is not None
    assert row.display_street == "103 Grouper Landing Rd"
    assert row.install_date.isoformat() == "2026-03-02T22:13:00+00:00"


def test_the_multi_install_address_keeps_the_more_recent_job(db_session) -> None:
    """One canonical address has two whole-system installs four days apart
    (most likely two separate units on one project). "Most recent first"
    means the April 22 job wins, not the April 20 one.
    """
    row = db_session.execute(
        text(
            "SELECT install_job_id, install_date FROM knowledge.install_dates "
            "WHERE canonical_id = 'cadr_760e6541cb725a108be9c7a874b15c8d'"
        )
    ).first()
    assert row is not None
    assert row.install_job_id == "job_27d5af789e6749f9a4eb552816ce4ff7"
    assert row.install_date.isoformat() == "2026-04-22T19:07:36+00:00"


def test_zone_installation_and_relocation_jobs_are_excluded(db_session) -> None:
    """Both contain the word "install" and were checked by hand and excluded:
    a zone/damper job on an existing system, and a relocation of an existing
    unit. Neither starts a fresh install clock.
    """
    excluded_job_ids = {
        row.id
        for row in db_session.execute(
            text(
                "SELECT id FROM source.jobs WHERE description LIKE "
                "'Zone System Installation%' OR description LIKE "
                "'System Relocation%'"
            )
        )
    }
    assert len(excluded_job_ids) == 2
    used_as_install_job = db_session.execute(
        text(
            "SELECT count(*) FROM knowledge.install_dates "
            "WHERE install_job_id = ANY(:ids)"
        ),
        {"ids": list(excluded_job_ids)},
    ).scalar_one()
    assert used_as_install_job == 0


def test_every_row_agrees_with_its_own_job(db_session) -> None:
    """install_date is always exactly that job's completed_at - no drift
    between the two once written.
    """
    mismatches = db_session.execute(
        text(
            "SELECT count(*) FROM knowledge.install_dates id "
            "JOIN source.jobs j ON j.id = id.install_job_id "
            "WHERE id.install_date != j.completed_at"
        )
    ).scalar_one()
    assert mismatches == 0


def test_every_install_job_matches_a_declared_prefix(db_session) -> None:
    bad = db_session.execute(
        text(
            "SELECT count(*) FROM knowledge.install_dates id "
            "JOIN source.jobs j ON j.id = id.install_job_id "
            "WHERE NOT (j.description LIKE 'System Installation%' "
            "        OR j.description LIKE 'New System Installation%' "
            "        OR j.description LIKE 'New Construction%')"
        )
    ).scalar_one()
    assert bad == 0
