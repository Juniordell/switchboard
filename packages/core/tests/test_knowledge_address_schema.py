"""Structural guards on the knowledge address schema. Metadata only, no
connection - same convention as `test_source_models.py`.
"""

from switchboard_core.db.base import KNOWLEDGE_SCHEMA
from switchboard_core.db.knowledge import AddressAlias, CanonicalAddress, InstallDate


def test_both_tables_are_in_the_knowledge_schema() -> None:
    assert CanonicalAddress.__table__.schema == KNOWLEDGE_SCHEMA
    assert AddressAlias.__table__.schema == KNOWLEDGE_SCHEMA


def test_canonical_addresses_has_a_trigram_index_on_street_normalized() -> None:
    indexes = CanonicalAddress.__table__.indexes
    trgm = next((i for i in indexes if "trgm" in i.name), None)
    assert trgm is not None, "no trigram index found on canonical_addresses"
    assert list(trgm.columns.keys()) == ["street_normalized"]
    assert trgm.dialect_options["postgresql"]["using"] == "gin"
    assert trgm.dialect_options["postgresql"]["ops"] == {
        "street_normalized": "gin_trgm_ops"
    }


def test_address_alias_references_canonical_addresses() -> None:
    fk_targets = {
        fk.target_fullname
        for col in AddressAlias.__table__.columns
        for fk in col.foreign_keys
    }
    assert f"{KNOWLEDGE_SCHEMA}.canonical_addresses.canonical_id" in fk_targets


def test_address_alias_references_the_source_customer_addresses_address_id() -> None:
    fk_targets = {
        fk.target_fullname
        for col in AddressAlias.__table__.columns
        for fk in col.foreign_keys
    }
    assert "source.customer_addresses.address_id" in fk_targets


def test_address_alias_primary_key_is_address_id_not_canonical_id() -> None:
    """address_id is the stable key (copied verbatim from source); canonical_id
    is derived from code and can change if the normaliser changes. See
    build_addresses.py's module docstring for why that distinction matters.
    """
    pk_columns = [c.name for c in AddressAlias.__table__.primary_key.columns]
    assert pk_columns == ["address_id"]


def test_install_dates_is_in_the_knowledge_schema() -> None:
    assert InstallDate.__table__.schema == KNOWLEDGE_SCHEMA


def test_install_dates_canonical_id_cascades_on_delete() -> None:
    """Every knowledge table is fully rebuilt from source on each load (see
    build_addresses.py); a stale install_dates row pointing at a
    canonical_addresses row about to be deleted and recomputed is not data
    worth protecting. Without the cascade, a second load fails outright with
    a foreign key violation - verified by loading twice, not inferred.
    """
    fk = next(
        fk
        for col in InstallDate.__table__.columns
        for fk in col.foreign_keys
        if fk.column.table.name == "canonical_addresses"
    )
    assert fk.ondelete == "CASCADE"


def test_install_dates_references_the_install_job() -> None:
    fk_targets = {
        fk.target_fullname
        for col in InstallDate.__table__.columns
        for fk in col.foreign_keys
    }
    assert "source.jobs.id" in fk_targets
