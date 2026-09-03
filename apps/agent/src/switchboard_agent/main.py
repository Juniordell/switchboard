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

import logging

from livekit.agents import (
    AgentServer,
    AgentSession,
    JobContext,
    cli,
    inference,
)
from livekit.agents.voice.room_io import RoomOptions

from switchboard_agent.agents import TriageAgent

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
ENDPOINTING_MIN_DELAY = 1.0

#: How long a turn the detector is unsure about may wait.
ENDPOINTING_MAX_DELAY = 4.0

server = AgentServer()


@server.rtc_session(agent_name="switchboard")
async def entrypoint(ctx: JobContext) -> None:
    # The room name is the call id: every audit row and every line of the
    # tool call log traces back to this call (CLAUDE.md hard rule 5).
    call_id = ctx.room.name
    logger.info("call starting", extra={"call_id": call_id})

    session = AgentSession(
        stt=inference.STT(model=STT_MODEL, language="en"),
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


def main() -> None:
    cli.run_app(server)


if __name__ == "__main__":
    main()
