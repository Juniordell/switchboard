"""The voice agent: Triage, Service and Dispatch over one cascade pipeline.

The call opens on Triage, which holds only `resolve_address` and
`resolve_customer` - no job, invoice, note or schedule data is reachable
before identity resolves. Triage hands to Service by returning the next
agent from inside a tool call; Service hands to Dispatch the same way when
the caller wants something written.

Service cannot hold a write tool, and that is enforced where the classes are
defined, not here and not in a prompt - see `switchboard_agent.agents`.

**`AgentServer` with `@server.rtc_session`**, not the `WorkerOptions` +
`cli.run_app(WorkerOptions(...))` shape the PyPI readme still shows. The
entrypoint is registered by the decorator and `cli.run_app` takes the
server.

**Cascade, not speech-to-speech**, for the reason in
`docs/ARCHITECTURE.md`: this agent's job is tool calling, and the harness
and the audit trail both run on text. Every stage is LiveKit Inference, so
there is one credential and no per-provider plugin.

**Keyterms.** `docs/DATA.md` measured the nine terms techs actually write,
and they are exactly the words a general STT model gets wrong on a phone
line - "freon", "R410", "capacitor", "condenser". Feeding them as keyterms
is the cheapest accuracy win available, and it comes from measured data
rather than from a guess about HVAC vocabulary.
"""

import asyncio
import datetime
import logging
import uuid

from livekit.agents import (
    AgentServer,
    AgentSession,
    JobContext,
    cli,
    inference,
)
from livekit.agents import telemetry as lk_telemetry
from livekit.agents.voice.room_io import RoomOptions
from sqlalchemy import text

from switchboard_agent.agents import TriageAgent
from switchboard_agent.transcript import capture_transcript
from switchboard_core.db.session import create_db_engine, session_factory
from switchboard_core.observability import record_tool_calls
from switchboard_core.telemetry import (
    current_traceparent,
    genai_span,
    tracer_provider,
)

logger = logging.getLogger("switchboard_agent")

#: The nine most frequent terms in the notes, from `docs/DATA.md`'s measured
#: table. Occurrence counts, not note counts - the table gives both, and
#: keyterm weighting wants how often a word is said, not how many notes
#: mention it. "not cooling" is a phrase and is kept as one.
KEYTERMS = [
    "drain",
    "not cooling",
    "thermostat",
    "condenser",
    "compressor",
    "warranty",
    "capacitor",
    "freon",
    "R410",
    # Not from the frequency table: the company's own name, which no STT
    # model has any reason to know.
    "Gulf Breeze Air",
]

STT_MODEL = "deepgram/nova-3"
LLM_MODEL = "openai/gpt-4o-mini"
TTS_MODEL = "inworld/inworld-tts-2"
TTS_VOICE = "Ashley"

#: Seconds before a turn is committed. Two real calls answered
#: half-finished questions - "When were" scored 0.87 on end-of-turn, "Am I
#: still on the" scored 0.94 - so the detector's confidence is not the thing
#: to trust here. This buys the caller a pause between the question and the
#: address, and it is a genuine trade: every turn now waits this much longer
#: before the agent starts speaking.
#: Raised from 1.0 after a production call was cut mid-address: the caller
#: said "eighty five oh four East Old Mangrove", the turn was committed
#: during the pause, and the agent searched on the fragment. LiveKit's own
#: warning names this - "transcript arrives after turn has been committed,
#: consider raising min_delay to accommodate a slow stt" - and reading
#: `voice/audio_recognition.py` confirms it: the turn is committed on
#: timing, the STT's final transcript lands after the commit and is then
#: discarded because there is no prediction left to attach it to.
#:
#: This is the floor, not the wait. Endpointing is `dynamic`, so the
#: effective delay is learned upward from the caller's own pauses. But it
#: only learns from pauses where the agent did not speak, so it could not
#: learn its way out of this one - the agent had already answered.
#:
#: The cost is real and paid on every turn: 0.6s more before the agent
#: starts speaking. Published guidance puts a good p95 under ~1.4s, so
#: this spends most of that budget. Deliberate: half a second of waiting
#: is cheaper than reading a caller another property's history.
ENDPOINTING_MIN_DELAY = 1.6

#: How long a turn the detector is unsure about may wait.
ENDPOINTING_MAX_DELAY = 4.0

server = AgentServer()


def _open_call(call_id: str, caller: str | None, traceparent: str | None) -> None:
    """Record the call, so the dashboard has something to group by.

    Best effort. A database the agent cannot reach is a reason to answer
    the phone without a dashboard, not a reason to drop the call.
    """
    try:
        sessions = session_factory(create_db_engine())
        with sessions() as session, session.begin():
            session.execute(
                text(
                    "INSERT INTO ops.calls (call_id, caller, started_at, traceparent) "
                    "VALUES (:c, :caller, :now, :tp) "
                    "ON CONFLICT (call_id) DO NOTHING"
                ),
                {
                    "c": call_id,
                    "caller": caller,
                    "now": datetime.datetime.now(datetime.UTC),
                    "tp": traceparent,
                },
            )
    except Exception:
        logger.exception("could not record the start of call %s", call_id)


def _close_call(call_id: str) -> None:
    """Close the call row and queue it for the async agents.

    T7.1: the trigger is the session ending. Queued in the same transaction
    that marks the call over, so there is no window where a call is
    finished and nothing is going to read it.
    """
    # Never let teardown fail a call that already happened - but say so.
    # This ran silently for one production call: the shutdown callback was
    # dying upstream, and nothing here could have reported it either.
    try:
        sessions = session_factory(create_db_engine())
        with sessions() as session, session.begin():
            session.execute(
                text("UPDATE ops.calls SET ended_at = :now WHERE call_id = :c"),
                {"c": call_id, "now": datetime.datetime.now(datetime.UTC)},
            )
            session.execute(
                text(
                    # `:c` appears twice, and Postgres deduces a different
                    # type for each - varchar from the INSERT target, text
                    # from the comparison - then refuses the statement as
                    # AmbiguousParameter. The cast pins it. Same fix as the
                    # customer_id cast in T3.2; Postgres 18 on Neon is
                    # stricter here than the 17 we develop against.
                    "INSERT INTO ops.async_jobs (id, call_id, kind, status) "
                    "SELECT :id, CAST(:c AS varchar), 'extract', 'queued' "
                    # Any extract job for this call, whatever its status.
                    # It used to read `status IN ('queued','running')`, which
                    # is a race the worker wins: the close in _run_call
                    # queues, the worker finishes in under ten seconds, and
                    # the shutdown backstop then sees nothing outstanding and
                    # queues a second one. A real call was extracted twice.
                    # A transcript is extracted once, ever.
                    "WHERE NOT EXISTS ("
                    "  SELECT 1 FROM ops.async_jobs "
                    "  WHERE call_id = CAST(:c AS varchar) "
                    "  AND kind = 'extract')"
                ),
                {"id": f"job_{uuid.uuid4().hex}", "c": call_id},
            )
        logger.info("closed call %s and queued it for extraction", call_id)
    except Exception:
        logger.exception("could not close call %s or queue it for extraction", call_id)


@server.rtc_session(agent_name="switchboard")
async def entrypoint(ctx: JobContext) -> None:
    # The room name is the call id: every audit row and every line of the
    # tool call log traces back to this call (CLAUDE.md hard rule 5).
    call_id = ctx.room.name
    logger.info("call starting", extra={"call_id": call_id})

    # Turn the tool call log into rows. The decorator keeps logging; this
    # is what lets T6.2's stream see it from another process, and it is
    # installed here rather than in the contract so the test suite does not
    # write rows it never asked for.
    record_tool_calls()

    # LiveKit instruments its own pipeline; giving it our provider puts the
    # STT, LLM and TTS spans in the same trace as everything below rather
    # than in one of its own.
    provider = tracer_provider()
    lk_telemetry.set_tracer_provider(provider, metadata={"call_id": call_id})

    with genai_span(
        "call",
        operation="invoke_agent",
        model=LLM_MODEL,
        call_id=call_id,
        attributes={"switchboard.caller": _caller_from(call_id) or "unknown"},
    ):
        _open_call(call_id, _caller_from(call_id), current_traceparent())
        # The backstop, for the case where _run_call raises: the close
        # below would be skipped, and a call that happened must still be
        # closed and queued.
        #
        # `to_thread`, not a bare lambda: LiveKit awaits what the callback
        # returns, so a sync function here raises `await None` and the whole
        # shutdown dies before it runs. It also keeps psycopg's blocking
        # work off the event loop, which is right regardless.
        ctx.add_shutdown_callback(lambda: asyncio.to_thread(_close_call, call_id))

        await _run_call(ctx, call_id)

        # Close here, not only in the shutdown callback. Shutdown runs while
        # the process is being torn down, and two round trips to a remote
        # database did not finish before it went away - two production calls
        # ended with ended_at still null and no extract job queued, and the
        # second left no log at all to say why. This runs while the process
        # is unambiguously alive. `_close_call` is idempotent (the UPDATE is
        # by key, the INSERT is guarded by NOT EXISTS), so the backstop
        # firing as well costs nothing.
        await asyncio.to_thread(_close_call, call_id)


async def _run_call(ctx: JobContext, call_id: str) -> None:

    session = AgentSession(
        stt=inference.STT(
            model=STT_MODEL,
            language="en",
            # Deepgram formats spoken numbers where it still has the audio,
            # which is earlier and better informed than our normaliser can
            # be from words alone. Their own example is this exact problem:
            # "one two three southeast main street" -> "123 Southeast Main
            # Street". A caller on this line says an address in almost every
            # call, so this is not a marginal setting.
            #
            # `numerals` converts digit words on its own; `smart_format`
            # implies it and adds the address/date/currency shaping. Both
            # are named so the intent survives a future reader.
            extra_kwargs={"smart_format": True, "numerals": True},
        ),
        llm=inference.LLM(model=LLM_MODEL),
        tts=inference.TTS(model=TTS_MODEL, voice=TTS_VOICE),
        stt_context_options={"keyterms": KEYTERMS},
        # min_endpointing_delay is deprecated in 1.7.1 in favour of this.
        turn_handling={
            "endpointing": {
                "mode": "dynamic",
                "min_delay": ENDPOINTING_MIN_DELAY,
                "max_delay": ENDPOINTING_MAX_DELAY,
            }
        },
    )

    capture_transcript(session, call_id)

    await session.start(
        agent=TriageAgent(call_id),
        room=ctx.room,
        room_options=RoomOptions(),
    )

    await session.generate_reply(
        instructions=(
            "Greet the caller as Gulf Breeze Air and ask how you can help. "
            "Do not ask for their address yet unless they pause."
        )
    )


def _caller_from(room_name: str) -> str | None:
    """The dispatch rule names rooms `call-_<caller>_<random>`, so the
    caller's number is already in the room name."""
    parts = room_name.split("_")
    return parts[1] if len(parts) >= 3 and parts[1].startswith("+") else None


def main() -> None:
    cli.run_app(server)


if __name__ == "__main__":
    main()
