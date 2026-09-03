"""`job_canonical_id` - resolving a job to a canonical address from its own
flattened columns, without going through `address_alias`. No database beyond
what's needed to check against a real `knowledge.canonical_addresses`.
"""

from sqlalchemy import text

from switchboard_core.knowledge import job_canonical_id, jobs_at_canonical_address


def test_agrees_with_address_alias_on_every_job(db_session) -> None:
    """The general claim job_address.py's docstring makes, checked exactly:
    zero mismatches across all 1,992 jobs.
    """
    rows = db_session.execute(
        text(
            "SELECT address_id, address_street, address_street_line_2, address_zip "
            "FROM source.jobs"
        )
    ).all()
    mismatches = 0
    for row in rows:
        computed = job_canonical_id(
            row.address_street, row.address_street_line_2, row.address_zip
        )
        if row.address_id:
            via_alias = db_session.execute(
                text(
                    "SELECT canonical_id FROM knowledge.address_alias "
                    "WHERE address_id = :a"
                ),
                {"a": row.address_id},
            ).scalar()
            if computed != via_alias:
                mismatches += 1
    assert mismatches == 0


def test_resolves_a_null_address_id_job_with_a_real_street(db_session) -> None:
    """job_489acf8ec56d has no address_id but a real street that matches an
    existing customer_addresses row - resolves same as any other job.
    """
    row = db_session.execute(
        text(
            "SELECT address_street, address_street_line_2, address_zip "
            "FROM source.jobs WHERE id = 'job_489acf8ec56d4145b47ea9ad24749f58'"
        )
    ).first()
    assert row is not None
    canonical_id = job_canonical_id(
        row.address_street, row.address_street_line_2, row.address_zip
    )
    exists = db_session.execute(
        text("SELECT 1 FROM knowledge.canonical_addresses WHERE canonical_id = :c"),
        {"c": canonical_id},
    ).scalar()
    assert exists == 1


def test_returns_none_for_a_fully_blank_address() -> None:
    assert job_canonical_id(None, None, None) is None


def test_does_not_resolve_the_genuinely_orphaned_job(db_session) -> None:
    """69 Plumeria Glen Drive: a real street, but no customer_addresses row
    anywhere carries it. Computes a key, but that key matches nothing.
    """
    canonical_id = job_canonical_id("69 Plumeria Glen Drive", "Cottage 20 A", "33182")
    assert canonical_id is not None
    exists = db_session.execute(
        text("SELECT 1 FROM knowledge.canonical_addresses WHERE canonical_id = :c"),
        {"c": canonical_id},
    ).scalar()
    assert exists is None


def test_does_not_resolve_the_garbage_address_id_job(db_session) -> None:
    """job_0feecbb8c89f's address_id points at the one all-blank
    customer_addresses row, which T2.1 excludes from canonicalisation
    entirely - its own flattened columns are equally blank.
    """
    row = db_session.execute(
        text(
            "SELECT address_street, address_street_line_2, address_zip "
            "FROM source.jobs WHERE id = 'job_0feecbb8c89f4d3b9f1b73c4c0eb594b'"
        )
    ).first()
    assert row is not None
    assert (
        job_canonical_id(row.address_street, row.address_street_line_2, row.address_zip)
        is None
    )


def test_jobs_at_canonical_address_finds_both_paths(db_session) -> None:
    """The 1,988 jobs with an address_id go through address_alias; the null
    ones go through the direct computation. 46 Bougainvillea Glen Road has
    one of each: job_489acf8ec56d... (null address_id) and at least one
    normal job sharing the same canonical address.
    """
    canonical_id = job_canonical_id("46 Bougainvillea Glen Road", None, "33162")
    job_ids = jobs_at_canonical_address(db_session, canonical_id)
    assert "job_489acf8ec56d4145b47ea9ad24749f58" in job_ids
    assert len(job_ids) >= 2


def test_jobs_at_canonical_address_finds_the_orphan_by_its_own_computation(
    db_session,
) -> None:
    """ "Orphan" means no `knowledge.canonical_addresses` row exists for this
    key - it does not mean the job itself is unreachable. Passing the
    orphan's own freshly computed canonical_id finds the orphan job, which
    is self-consistent: `jobs_at_canonical_address` never queries
    `canonical_addresses`, only jobs' own columns.
    """
    canonical_id = job_canonical_id("69 Plumeria Glen Drive", "Cottage 20 A", "33182")
    job_ids = jobs_at_canonical_address(db_session, canonical_id)
    assert job_ids == ["job_a8edd70d8b7c48928bce658029e854f1"]
