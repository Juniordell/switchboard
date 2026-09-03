"""CLAUDE.md hard rule 4, as a test rather than a convention.

"Customer-record write tools live only on the Dispatch agent. No read-path
agent may import or expose them." The rule is about who can reach a write,
so the assertions are about the registries an agent binds from and the
`agent` each tool was declared with - not about anyone's good intentions.

`transfer_to_human` is deliberately absent from both: it is `control`, not
`write` (`docs/AGENTS.md`), and it does not exist yet - T5.4 builds it.
"""

import switchboard_core.tools as tools_package
from switchboard_core.tools import READ_TOOLS, WRITE_TOOLS

EXPECTED_WRITE_TOOLS = {"book_job", "move_job", "add_note"}


class TestTheRegistriesAreDisjoint:
    def test_no_write_tool_is_reachable_through_read_tools(self) -> None:
        assert set(READ_TOOLS) & set(WRITE_TOOLS) == set()

    def test_write_tools_are_exactly_the_three_declared_ones(self) -> None:
        """A new write tool has to be added here on purpose, which is a
        diff a reviewer sees."""
        assert set(WRITE_TOOLS) == EXPECTED_WRITE_TOOLS

    def test_no_read_tool_shares_a_name_with_a_write_tool(self) -> None:
        assert not any(name in READ_TOOLS for name in EXPECTED_WRITE_TOOLS)


class TestEveryWriteToolIsDispatch:
    def test_each_write_logs_itself_as_dispatch(self, caplog, write_session) -> None:
        """The `agent` a tool was declared with is what lands in the call
        log, so asserting on the log asserts on the declaration."""
        import datetime
        import json
        import logging

        from switchboard_core.tools import BookJobRequest, book_job

        with caplog.at_level(logging.INFO, logger="switchboard_core.tools"):
            book_job(
                BookJobRequest(
                    customer_id="cus_x",
                    scheduled_start=datetime.datetime(
                        2026, 10, 1, 14, 0, tzinfo=datetime.UTC
                    ),
                    description="guard test",
                    display_address="1 Test St",
                    spoken_confirmation="yes that works",
                ),
                call_id="call_guard",
                session=write_session,
            )
        record = json.loads(caplog.records[0].message)
        assert record["agent"] == "Dispatch"


class TestReadPathCannotReachAWrite:
    def test_the_read_registry_holds_only_read_agents(self) -> None:
        """Triage and Service hold reads. Dispatch appears in READ_TOOLS
        only for `find_availability`, which is a SQL read that happens to
        live on Dispatch - it mutates nothing."""
        assert "find_availability" in READ_TOOLS
        assert "find_availability" not in WRITE_TOOLS

    def test_write_tools_are_not_exported_as_read_tools(self) -> None:
        for name in EXPECTED_WRITE_TOOLS:
            assert getattr(tools_package, name) is WRITE_TOOLS[name]
            assert WRITE_TOOLS[name] not in READ_TOOLS.values()
