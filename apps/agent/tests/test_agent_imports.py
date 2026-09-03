"""The voice agent: the server shape, the tools it binds, the keyterms.

No LiveKit room is joined here. What is asserted is everything that can be
wrong before a call ever connects - the wrong entrypoint pattern, a tool set
that differs from the one Layer 1 graded, or keyterms that have drifted from
the measured table they came from.
"""

import pathlib
import re

from livekit.agents import AgentServer

from switchboard_agent import main
from switchboard_agent.text_client import NOT_MODEL_SELECTABLE
from switchboard_agent.tool_bridge import build_tools
from switchboard_core.tools import CONTROL_TOOLS, READ_TOOLS, WRITE_TOOLS

DATA_MD = pathlib.Path(__file__).parents[3] / "docs" / "DATA.md"


class TestTheServer:
    def test_it_is_an_agent_server_not_a_worker(self) -> None:
        """CLAUDE.md's stack pins AgentServer + @server.rtc_session. The
        WorkerOptions shape in the PyPI readme is the outdated one."""
        assert isinstance(main.server, AgentServer)

    def test_the_entrypoint_is_registered_by_the_decorator(self) -> None:
        assert callable(main.entrypoint)
        assert callable(main.main)


class TestTheToolsItBinds:
    def test_it_binds_every_tool_the_harness_graded(self) -> None:
        bound = {t.info.name for t in build_tools("call_test")}
        expected = (
            set(READ_TOOLS) | set(WRITE_TOOLS) | set(CONTROL_TOOLS)
        ) - NOT_MODEL_SELECTABLE
        assert bound == expected

    def test_transfer_is_bound_as_control(self) -> None:
        """Reachable from the read path: hard rule 4 is scoped to
        customer-record writes, and transfer_to_human mutates none."""
        bound = {t.info.name for t in build_tools("c", include_writes=False)}
        assert "transfer_to_human" in bound

    def test_it_does_not_offer_the_logic_tool(self) -> None:
        """Offering a tool in production that Layer 1 never offered would
        mean the harness graded a different agent than the one on the
        phone."""
        bound = {t.info.name for t in build_tools("call_test")}
        assert not (bound & NOT_MODEL_SELECTABLE)

    def test_the_write_tools_can_be_withheld(self) -> None:
        """T5.2 splits the agents; this is where hard rule 4's boundary
        starts."""
        read_only = {t.info.name for t in build_tools("c", include_writes=False)}
        assert not (read_only & set(WRITE_TOOLS))

    def test_each_carries_the_tool_s_own_json_schema(self) -> None:
        by_name = {t.info.name: t for t in build_tools("call_test")}
        schema = by_name["search_notes"].info.raw_schema["parameters"]
        assert "entity_id" in schema["properties"]
        assert "entity_id" in schema["required"]


class TestKeyterms:
    def test_every_measured_term_is_a_keyterm(self) -> None:
        """`docs/DATA.md` measured which words the techs actually write.
        If that table changes, these have to change with it - the whole
        point is that the hints come from data, not from a guess about
        HVAC vocabulary.
        """
        table = DATA_MD.read_text().split("## Frequent terms in notes")[1]
        measured = re.findall(r"^\| `([^`]+)` \|", table, flags=re.MULTILINE)
        assert len(measured) == 9, "DATA.md's frequent-terms table changed"

        lowered = {k.lower() for k in main.KEYTERMS}
        for term in measured:
            assert term.lower() in lowered, f"{term!r} is measured but not a keyterm"

    def test_the_company_name_is_included(self) -> None:
        """Not from the frequency table: no STT model has a reason to know
        it, and every caller says it."""
        assert "Gulf Breeze Air" in main.KEYTERMS

    def test_a_multi_word_term_is_kept_as_a_phrase(self) -> None:
        assert "not cooling" in main.KEYTERMS


class TestThePipelineIsCascade:
    def test_every_stage_is_livekit_inference(self) -> None:
        """One credential, no per-provider plugin. Cascade rather than
        speech-to-speech because the harness and the audit trail both run
        on text - see docs/ARCHITECTURE.md."""
        assert "/" in main.STT_MODEL
        assert "/" in main.LLM_MODEL
        assert "/" in main.TTS_MODEL


class TestHandoffsDoNotLeaveDeadAir:
    """The second real call left 29 seconds of silence after the handoff:
    Triage was told not to narrate it and nothing on the other side spoke.
    Every agent a caller can be handed *to* must open its own turn."""

    def test_service_speaks_on_arrival(self) -> None:
        from switchboard_agent.agents import ServiceAgent

        assert "on_enter" in ServiceAgent.__dict__

    def test_dispatch_speaks_on_arrival(self) -> None:
        from switchboard_agent.agents import DispatchAgent

        assert "on_enter" in DispatchAgent.__dict__

    def test_triage_does_not_need_one(self) -> None:
        """Nobody is handed to Triage; the entrypoint greets for it."""
        from switchboard_agent.agents import TriageAgent

        assert "on_enter" not in TriageAgent.__dict__
