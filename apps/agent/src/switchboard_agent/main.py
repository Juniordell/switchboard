"""The voice agent: one agent, cascade pipeline, every tool bound.

T5.1 is deliberately a single agent. The Triage / Service / Dispatch split
and its permissions boundary arrive at T5.2; what this proves is that the
pipeline runs, the tools bind, and a call can reach them.

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
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    RoomInputOptions,
    cli,
    inference,
)

from switchboard_agent.tool_bridge import build_tools

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

INSTRUCTIONS = """You are the front desk for Gulf Breeze Air, an HVAC company \
in Miami. You are on a phone call. Be brief: one or two sentences, no lists, \
no markdown.

How to work:
- Dates, counts, schedules, balances and warranty come from the SQL tools,
  never from note search. Never state one from memory.
- Resolve the address or the customer before reading any job, invoice, note
  or schedule data.
- When a tool comes back with must_ask, ask the caller which one they mean.
  Never pick for them.
- Speak the JOB number to callers. An invoice number is spoken only when
  citing an invoice, and is named as an invoice number.
- A note has no date of its own. Date it by the visit: "from the visit on
  14 June", never "a note from 14 June".
- Never book or change anything without the caller saying yes in that turn,
  and pass their own words as the confirmation.
- Warranty at levels 4, 5 or 6 is spoken as uncertain and offered for a
  human to check. "Warranty Complete" never means coverage ended.
- If no tool grounds the answer, say so and offer to pass them to someone.
  Refusing is a correct answer.

Say hello, say you are Gulf Breeze Air, and ask how you can help."""

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
    )

    await session.start(
        agent=Agent(instructions=INSTRUCTIONS, tools=build_tools(call_id)),
        room=ctx.room,
        room_input_options=RoomInputOptions(),
    )

    await session.generate_reply(
        instructions="Greet the caller as Gulf Breeze Air and ask how you can help."
    )


def main() -> None:
    cli.run_app(server)


if __name__ == "__main__":
    main()
