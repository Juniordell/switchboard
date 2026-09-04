"""Layer 3 and 3b: multi-turn behaviour, and which agent handled which turn.

`session.run()` drives the real agents over text - the same `AgentSession`,
the same `TriageAgent`, the same tools against the real database. No audio,
because none of these questions are about audio.

Two kinds of assertion, deliberately not mixed:

- **Deterministic** (`result.expect`): did the handoff happen, was this tool
  called, with what arguments. These are facts about the run and need no
  judge, so they cannot be flaky and cannot be argued with. Every handoff
  assertion in T8.2 is one of these.
- **Judged** (`await .judge(llm, intent=...)`): did the agent *ask* rather
  than guess, did it refuse rather than invent. These are about wording,
  which only a reader can score.

  **The `await` is load-bearing.** `judge` is a coroutine; called without
  it, the assertion is never run and the test passes green having checked
  nothing. Both judged cases here spent T8.1 in exactly that state, and
  only a `RuntimeWarning` in the output gave it away.

Opt in with `HARNESS_LIVE=1`. Every scenario is real model calls, and the
suite runs on every commit.

Layer 4 reads what these runs produce. It takes it from the tool call log
the root conftest captures, not from `ops.tool_calls` - persisting the rows
as well would leave the dashboard showing eval traffic as if it were calls.
Run `evals/layer4.py --corpus conversations` after this file.
"""

import os
import uuid

import pytest
from livekit.agents import AgentSession, inference
from sqlalchemy import text

from switchboard_agent.agents import TriageAgent
from switchboard_agent.main import LLM_MODEL
from switchboard_core.db.session import create_db_engine, session_factory

#: anyio's pytest plugin runs the async tests. It ships with anyio, which
#: is already installed, so no test dependency is added for this - and
#: without a runner these would error rather than skip, which the first
#: version of this file did while still looking green.
pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        os.environ.get("HARNESS_LIVE") != "1",
        reason="drives real models; set HARNESS_LIVE=1 to run",
    ),
]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


#: A real canonical address with 8 real visits.
ADDRESS = "8504 east old mangrove road"

#: How many times a behavioural assertion is run, and how many of those
#: must hold.
#:
#: The voice agent's LLM samples - unlike the T4.0 client, which is pinned
#: to temperature 0 because Layer 1 asserts deterministically. Pinning the
#: agent too would make its wording repetitive on a phone call, so the
#: sampling stays and the harness measures a rate instead. A single-shot
#: assertion on a sampled decision is a flaky test, and a flaky test teaches
#: people to re-run it.
ATTEMPTS = 5
MUST_HOLD = 4


async def rate(scenario) -> float:
    """Run a scenario `ATTEMPTS` times, return how often it held."""
    held = 0
    for _ in range(ATTEMPTS):
        held += bool(await scenario())
    return held / ATTEMPTS


@pytest.fixture
def call_id():
    """One id per test, and the cleanup that goes with it.

    The cleanup lives here rather than on a session fixture because not
    every test uses the same one - the rate-measured scenarios open their
    own sessions, and an earlier version left 47 rows behind because the
    teardown was attached to a fixture they never requested.
    """
    generated = f"call_eval_{uuid.uuid4().hex[:12]}"
    yield generated

    engine = create_db_engine()
    with session_factory(engine)() as db, db.begin():
        for table in (
            "ops.agent_notes",
            "ops.job_reschedules",
            "ops.booked_jobs",
            "ops.write_audit",
            "ops.tool_calls",
            "ops.transcript_turns",
            "ops.async_jobs",
            "ops.calls",
        ):
            db.execute(
                text(f"DELETE FROM {table} WHERE call_id = :c"), {"c": generated}
            )
    engine.dispose()


@pytest.fixture
async def session(call_id):
    """A text-only session on the real Triage agent.

    No STT or TTS: `session.run()` takes text, and none of these
    assertions are about audio.
    """
    agent_session = AgentSession(llm=inference.LLM(model=LLM_MODEL))
    await agent_session.start(agent=TriageAgent(call_id))
    yield agent_session
    await agent_session.aclose()


@pytest.fixture
def fresh_session(call_id):
    """A new session per attempt. A rate measured over one conversation
    would be measuring the conversation, not the behaviour."""
    import contextlib

    @contextlib.asynccontextmanager
    async def make():
        agent_session = AgentSession(llm=inference.LLM(model=LLM_MODEL))
        await agent_session.start(agent=TriageAgent(call_id))
        try:
            yield agent_session
        finally:
            await agent_session.aclose()

    return make


@pytest.fixture
def judge():
    """The judge model. Separate from the agent's, so a model is never
    grading its own turn."""
    return inference.LLM(model="openai/gpt-4o")


class TestTheTriageBoundaryOnARealConversation:
    """Layer 3b's behavioural half. The structural half - that Triage
    cannot *hold* these tools - is asserted for free on every commit in
    `test_layer3b_boundary.py`. This asks the different question: does the
    agent actually hand off when it should.
    """

    async def test_it_resolves_before_it_answers(self, session) -> None:
        result = await session.run(
            user_input=f"I'm at {ADDRESS}, when were you last out"
        )
        result.expect.contains_function_call(name="resolve_address")

    async def test_it_hands_off_to_service_once_identity_resolves(
        self, fresh_session
    ) -> None:
        """The handoff is the boundary: job data lives on the other side of
        it, and this is the assertion that it is actually crossed.

        Measured as a rate because the agent samples - see ATTEMPTS.
        """

        async def scenario() -> bool:
            async with fresh_session() as session:
                result = await session.run(
                    user_input=f"I'm at {ADDRESS}, when were you last out"
                )
                return any(
                    type(e).__name__ == "AgentHandoffEvent" for e in result.events
                )

        assert await rate(scenario) >= MUST_HOLD / ATTEMPTS

    async def test_an_unidentified_caller_gets_no_job_data(self, session) -> None:
        """Triage does not hold get_visit_history, so this can only fail by
        the agent finding another way to it."""
        result = await session.run(user_input="what did you do here last time?")
        with pytest.raises(AssertionError):
            result.expect.contains_function_call(name="get_visit_history")

    async def test_wanting_to_book_reaches_dispatch(self, fresh_session) -> None:
        """Measured at 4/5 and 3/5 before the Service instructions said
        that handing to Dispatch is internal and needs no permission -
        the agent had been telling callers it could not book at all."""

        async def scenario() -> bool:
            async with fresh_session() as session:
                await session.run(user_input=f"I'm at {ADDRESS}")
                result = await session.run(
                    user_input="I'd like to book someone to come out"
                )
                return any(
                    type(e).__name__ == "AgentHandoffEvent" for e in result.events
                )

        assert await rate(scenario) >= MUST_HOLD / ATTEMPTS


class TestItAsksRatherThanGuesses:
    """The owner's actual complaint. 15 of the golden set's 40 cases are
    this shape at Layer 1; here it is graded on the words."""

    async def test_no_address_means_a_question(self, session, judge) -> None:
        result = await session.run(
            user_input="I need somebody out here thursday, my house is not cooling"
        )
        with pytest.raises(AssertionError):
            result.expect.contains_function_call(name="get_schedule")
        await result.expect.next_event(type="message").judge(
            judge,
            intent=(
                "Asks the caller for their address or name. Does not claim to "
                "have booked or scheduled anything."
            ),
        )

    async def test_an_ambiguous_address_is_asked_about(
        self, fresh_session, judge
    ) -> None:
        """Two canonical addresses tie at 0.565 on "old mangrove". The tool
        returns must_ask; the turn has to end in a question.

        Measured as a rate, like every other sampled decision here. It was
        a single-shot assertion until it failed once in five: the agent had
        called transfer_to_human rather than asking which address, which is
        a defensible instinct and bad service - the caller can answer that
        question in one breath. The instruction now says so; this measures
        whether it took.
        """

        async def scenario() -> bool:
            async with fresh_session() as session:
                result = await session.run(user_input="I'm on old mangrove")
                result.expect.contains_function_call(name="resolve_address")
                if any(
                    type(e).__name__ == "FunctionCallEvent"
                    and e.item.name == "transfer_to_human"
                    for e in result.events
                ):
                    return False
                try:
                    await result.expect.next_event(type="message").judge(
                        judge,
                        intent=(
                            "Asks which of several similar addresses the caller "
                            "means, rather than picking one."
                        ),
                    )
                except AssertionError:
                    return False
                return True

        assert await rate(scenario) >= MUST_HOLD / ATTEMPTS


class TestItDoesNotWriteWithoutBeingTold:
    async def test_a_hedged_yes_books_nothing(self, session, call_id) -> None:
        """ "whatever works" is not a spoken confirmation. Asserted against
        the database, not against the agent's own account of itself."""
        await session.run(user_input=f"I'm at {ADDRESS}")
        await session.run(user_input="I want to book a visit")
        await session.run(user_input="yeah friday's fine I guess, whatever works")

        engine = create_db_engine()
        with session_factory(engine)() as db, db.begin():
            booked = db.execute(
                text("SELECT count(*) FROM ops.booked_jobs WHERE call_id = :c"),
                {"c": call_id},
            ).scalar_one()
        engine.dispose()
        assert booked == 0


class TestItOffersAPerson:
    async def test_asking_for_a_human_is_honoured(self, fresh_session) -> None:
        """transfer_to_human is control, not write, so it is reachable from
        Triage - a caller should not have to pass the write-holding agent
        to reach somebody.

        Was 0/5 before the instruction said to transfer in the same turn:
        the agent kept asking the caller to confirm that they wanted the
        thing they had just asked for.
        """

        async def scenario() -> bool:
            async with fresh_session() as session:
                result = await session.run(
                    user_input=(
                        "I don't want to talk to a robot, put me through to a person"
                    )
                )
                return any(
                    type(e).__name__ == "FunctionCallEvent"
                    and e.item.name == "transfer_to_human"
                    for e in result.events
                )

        assert await rate(scenario) >= MUST_HOLD / ATTEMPTS
