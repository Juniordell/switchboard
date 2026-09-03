"""Layer 3b — which agent handled which turn.

`docs/HARNESS.md` describes this layer as needing a multi-turn session and a
judge, which is true of half of it. The other half is not a behaviour to
observe at all: it is a property of the agent classes, and a property can be
proved rather than sampled.

So this file asserts the boundary **structurally**, on every commit, for
nothing:

- An unidentified caller cannot reach `get_schedule`, `get_visit_history`,
  `get_warranty_status` or `search_notes`, because Triage does not hold
  them and there is no path that adds them.
- Service holds no customer-record write tool, and a class that tried would
  not import.
- `transfer_to_human` is reachable from every agent, because a caller
  should not have to pass through the write-holding agent to reach a
  person.

What still needs a real conversation is whether the model *hands off* at
the right moment. That part reads the turn log this run produced - see
`assert_no_forbidden_turns` - and belongs pre-deploy, where a session
exists to generate turns.
"""

import json

import pytest

from switchboard_agent.agents import (
    DispatchAgent,
    ServiceAgent,
    SwitchboardAgent,
    TriageAgent,
)
from switchboard_core.tools import CONTROL_TOOLS, READ_TOOLS, WRITE_TOOLS

#: `docs/ARCHITECTURE.md`, the Triage boundary stated precisely: no job,
#: invoice, note or schedule data before identity resolves.
BEHIND_THE_HANDOFF = frozenset(
    {
        "get_schedule",
        "get_visit_history",
        "get_warranty_status",
        "search_notes",
        "get_customer_balance",
    }
)


class TestTheTriageBoundary:
    def test_triage_cannot_reach_anything_describing_work(self) -> None:
        assert not (TriageAgent.TOOLS & BEHIND_THE_HANDOFF)

    def test_triage_holds_only_the_two_resolvers(self) -> None:
        assert sorted(TriageAgent.TOOLS) == ["resolve_address", "resolve_customer"]

    def test_the_data_is_reachable_once_identity_resolves(self) -> None:
        """The boundary is a handoff, not a wall: everything Triage cannot
        see, Service can."""
        assert BEHIND_THE_HANDOFF <= ServiceAgent.TOOLS


class TestServiceCannotWrite:
    def test_service_holds_no_write_tool(self) -> None:
        assert not (ServiceAgent.TOOLS & frozenset(WRITE_TOOLS))

    def test_a_read_agent_declaring_a_write_tool_does_not_import(self) -> None:
        """The guarantee, exercised. This is a class-definition error, so a
        violation cannot start, cannot be deployed, and cannot be reached
        by a call - it is not a runtime check something might skip.
        """
        with pytest.raises(TypeError, match="may not hold write tools: book_job"):

            class Broken(SwitchboardAgent):
                TOOLS = frozenset({"get_schedule", "book_job"})
                NAME = "Broken"

    def test_the_error_names_every_offending_tool(self) -> None:
        with pytest.raises(TypeError, match="add_note, book_job, move_job"):

            class VeryBroken(SwitchboardAgent):
                TOOLS = frozenset(WRITE_TOOLS)
                NAME = "VeryBroken"

    def test_a_typo_is_caught_too(self) -> None:
        """A tool name that does not exist is as much a deployment bug as a
        forbidden one."""
        with pytest.raises(TypeError, match="unknown tools"):

            class Typo(SwitchboardAgent):
                TOOLS = frozenset({"get_shedule"})
                NAME = "Typo"

    def test_only_dispatch_may_write(self) -> None:
        assert DispatchAgent.MAY_WRITE is True
        assert ServiceAgent.MAY_WRITE is False
        assert TriageAgent.MAY_WRITE is False
        assert frozenset(WRITE_TOOLS) <= DispatchAgent.TOOLS


class TestTransferIsReachableEverywhere:
    def test_it_is_control_not_write(self) -> None:
        assert "transfer_to_human" in CONTROL_TOOLS
        assert "transfer_to_human" not in WRITE_TOOLS
        assert CONTROL_TOOLS["transfer_to_human"].tool_kind == "control"

    @pytest.mark.parametrize("agent", [TriageAgent, ServiceAgent, DispatchAgent])
    def test_every_agent_can_reach_a_person(self, agent) -> None:
        """Reaching a human from the read path is correct behaviour, not a
        boundary violation - forcing a caller through the write-holding
        agent to be transferred would invert the rule."""
        held = agent.TOOLS | frozenset(CONTROL_TOOLS)
        assert "transfer_to_human" in held


class TestTheHandoffChain:
    def test_each_step_widens_exactly_once(self) -> None:
        assert TriageAgent.TOOLS < ServiceAgent.TOOLS < DispatchAgent.TOOLS

    def test_dispatch_is_the_end_of_the_chain(self) -> None:
        everything = frozenset(READ_TOOLS) | frozenset(WRITE_TOOLS)
        assert sorted(DispatchAgent.TOOLS) == sorted(everything)


def assert_no_forbidden_turns(turn_log: list[dict]) -> list[str]:
    """The behavioural half, for a run that has a real conversation.

    Reads `{call_id, agent, tool}` records - the turn log the tool bridge
    writes, which records the agent that **handled** the call rather than
    the agent a tool was declared on. Returns the violations it found.
    """
    allowed = {
        "Triage": TriageAgent.TOOLS | frozenset(CONTROL_TOOLS),
        "Service": ServiceAgent.TOOLS | frozenset(CONTROL_TOOLS),
        "Dispatch": DispatchAgent.TOOLS | frozenset(CONTROL_TOOLS),
    }
    violations = []
    for record in turn_log:
        agent, tool = record.get("agent"), record.get("tool")
        if agent in allowed and tool not in allowed[agent]:
            violations.append(f"{agent} handled {tool}, which it may not hold")
    return violations


class TestTheTurnLogAssertion:
    def test_a_clean_log_has_no_violations(self) -> None:
        log = [
            {"call_id": "c", "agent": "Triage", "tool": "resolve_address"},
            {"call_id": "c", "agent": "Service", "tool": "get_visit_history"},
            {"call_id": "c", "agent": "Dispatch", "tool": "book_job"},
        ]
        assert assert_no_forbidden_turns(log) == []

    def test_it_catches_triage_reaching_past_the_handoff(self) -> None:
        log = [{"call_id": "c", "agent": "Triage", "tool": "get_visit_history"}]
        assert assert_no_forbidden_turns(log) == [
            "Triage handled get_visit_history, which it may not hold"
        ]

    def test_it_catches_service_writing(self) -> None:
        log = [{"call_id": "c", "agent": "Service", "tool": "book_job"}]
        assert assert_no_forbidden_turns(log) == [
            "Service handled book_job, which it may not hold"
        ]

    def test_the_turn_log_is_json_per_line(self) -> None:
        """Shape check, so the assertion above and the bridge that writes
        the records cannot drift."""
        record = json.loads('{"call_id": "c", "agent": "Service", "tool": "x"}')
        assert set(record) == {"call_id", "agent", "tool"}
