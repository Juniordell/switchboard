"""The shared machinery behind every write tool: a key, an audit row, and a
`NOTIFY` nobody has to remember to send.

**The retry guard is a unique constraint, not a lookup.** Checking for an
existing key before inserting is check-then-act: two retries of the same
turn can both find nothing and both book. `ops.write_audit.idempotency_key`
is `UNIQUE`, so the second insert conflicts and the tool reads back what the
first one wrote. The caller gets the original result with `replayed=True`,
never an error and never a second booking.

**Ids are derived from the key, not generated.** A retry of the same write
computes the same `job_id`, so the primary key on `ops.booked_jobs` is a
second, independent guard against a duplicate - and the caller who retries
gets back the id it was already told, rather than a new one for a row that
is the same appointment.

The audit row and the state change happen in one transaction. If the state
write fails, the audit row goes with it and a retry is free to proceed - an
audit row for a write that did not happen would be worse than none.
"""

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from switchboard_core.db.ops.write_audit import WriteAudit

#: Separator that cannot appear in an id, a slot or a call id, so
#: ("a", "bc") and ("ab", "c") can never collide into one key.
_SEPARATOR = "\x1f"


def idempotency_key(*parts: str) -> str:
    """A stable key from the arguments that define *the same write*.

    `docs/AGENTS.md` specifies `call_id + slot` for `book_job` and the same
    rules for `move_job`. `add_note` has no slot - the spec does not cover
    it - so it keys on the call, the job and the note's content, which is
    the same principle: retrying one turn must not append the note twice.
    """
    return hashlib.sha256(_SEPARATOR.join(parts).encode()).hexdigest()


def derived_id(prefix: str, key: str) -> str:
    """A deterministic id for a row created by a keyed write.

    Same key, same id, so a retry lands on the primary key rather than
    creating a second row that is the same appointment under a new name.
    """
    return f"{prefix}_{key[:24]}"


def record_write(
    session: Session,
    *,
    key: str,
    call_id: str,
    agent: str,
    tool: str,
    action: str,
    new_values: dict[str, Any],
    job_id: str | None = None,
    old_values: dict[str, Any] | None = None,
    spoken_confirmation: str | None = None,
) -> tuple[WriteAudit, bool]:
    """Insert the audit row, or find the one a previous attempt wrote.

    Returns `(row, replayed)`. `replayed=True` means this exact write has
    already happened and the caller must not perform it again.
    """
    statement = (
        insert(WriteAudit)
        .values(
            id=derived_id("wrt", key),
            idempotency_key=key,
            call_id=call_id,
            agent=agent,
            tool=tool,
            action=action,
            job_id=job_id,
            old_values=old_values,
            new_values=new_values,
            spoken_confirmation=spoken_confirmation,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(WriteAudit.id)
    )

    inserted = session.execute(statement).scalar_one_or_none()
    existing = session.execute(
        select(WriteAudit).where(WriteAudit.idempotency_key == key)
    ).scalar_one()

    return existing, inserted is None
