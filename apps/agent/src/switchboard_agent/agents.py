"""Triage, Service and Dispatch, split on the permissions boundary.

How Service is stopped from writing
-----------------------------------
Not by a prompt. An agent declares the tools it may hold as a **class
attribute**, and `__init_subclass__` rejects the class at definition time if
a read-path agent names a customer-record write tool:

    class Broken(SwitchboardAgent):
        TOOLS = frozenset({"get_schedule", "book_job"})
        # TypeError at import: Broken may not hold write tools: book_job

That fires when the module is imported, so a violation cannot start, cannot
be deployed, and cannot be reached by a call. It is not a check the agent
performs at runtime and might skip - the process does not come up.

The tool list is then **derived** from that validated attribute rather than
passed in, so there is no argument for a caller to get wrong. There is no
code path that hands Service a write tool, because there is no parameter
that could carry one.

`transfer_to_human` is `control`, not `write`, and every agent holds it:
hard rule 4 is scoped to customer-record writes, and making a caller reach
the write-holding agent in order to be handed to a person would invert the
boundary it protects.
"""

from typing import ClassVar

from livekit.agents import Agent, function_tool

from switchboard_agent.tool_bridge import build_tools_for
from switchboard_core.tools import CONTROL_TOOLS, READ_TOOLS, WRITE_TOOLS

#: `docs/ARCHITECTURE.md`: Triage returns address and customer candidates
#: with confidence and nothing else. No history, no balance, no note text,
#: no appointment - everything describing work done or booked is behind the
#: handoff.
TRIAGE_TOOLS = frozenset({"resolve_address", "resolve_customer"})

#: Every read tool. Service handles most calls and holds no write.
SERVICE_TOOLS = frozenset(READ_TOOLS)

#: Reads plus the customer-record writes.
DISPATCH_TOOLS = frozenset(READ_TOOLS) | frozenset(WRITE_TOOLS)


class SwitchboardAgent(Agent):
    """Base for the three agents. Enforces the permissions boundary."""

    #: The tools this agent class may hold. Validated below.
    TOOLS: ClassVar[frozenset[str]] = frozenset()

    #: Only Dispatch sets this. Nothing else may name a write tool.
    MAY_WRITE: ClassVar[bool] = False

    #: What the call log and Layer 3b call this agent.
    NAME: ClassVar[str] = "unknown"

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        forbidden = cls.TOOLS & frozenset(WRITE_TOOLS)
        if forbidden and not cls.MAY_WRITE:
            raise TypeError(
                f"{cls.__name__} may not hold write tools: "
                f"{', '.join(sorted(forbidden))}. CLAUDE.md hard rule 4 keeps "
                f"customer-record writes on Dispatch alone."
            )
        unknown = cls.TOOLS - (
            frozenset(READ_TOOLS) | frozenset(WRITE_TOOLS) | frozenset(CONTROL_TOOLS)
        )
        if unknown:
            raise TypeError(f"{cls.__name__} names unknown tools: {sorted(unknown)}")

    def __init__(self, *, instructions: str, call_id: str) -> None:
        # Derived from the validated class attribute, never passed in:
        # there is no argument here that could carry a write tool into a
        # read-path agent.
        super().__init__(
            instructions=instructions,
            tools=build_tools_for(
                self.NAME, sorted(self.TOOLS | frozenset(CONTROL_TOOLS)), call_id
            ),
        )
        self.call_id = call_id


_SHARED_RULES = """
You are on a phone call for Gulf Breeze Air, an HVAC company in Miami. Be
brief: one or two sentences, no lists, no markdown.

Always:
- Dates, counts, schedules, balances and warranty come from tools, never
  from memory.
- When a tool comes back with must_ask, ask the caller which one they mean.
  Never pick for them, and never transfer instead of asking - the caller
  can answer "which of these two" in one breath, and handing that to a
  person is worse service than asking.
- Read a house number back before you act on it, digit by digit: "eight
  five zero four, is that right?" Speech-to-text mangles spoken numbers,
  and one wrong digit is another family's property. Read back the number
  only - not the whole address, and not every field you collected.
- Speak the JOB number. An invoice number is spoken only when citing an
  invoice, and is named as one.
- A note has no date of its own. Date it by the visit: "from the visit on
  14 June", never "a note from 14 June".
- Warranty coverage `was_covered` is past tense and must be spoken that
  way: the part *was* covered on that visit, which is not the same as
  covered today. Never turn it into "it's under warranty". Say what the
  evidence is and offer to have someone confirm current coverage.
- If no tool grounds the answer, say so and offer to pass them to a person.
  Refusing is a correct answer.
- When the caller asks for a person, call transfer_to_human in that same
  turn. Do not ask them to confirm that they want what they just asked for.
  Also use it for Sunday or after-hours work, and when you have promised
  something you cannot ground. Carry the reason and every promise you made.
"""


class TriageAgent(SwitchboardAgent):
    """Establishes who is calling. Holds nothing that describes work."""

    TOOLS = TRIAGE_TOOLS
    NAME = "Triage"

    def __init__(self, call_id: str) -> None:
        super().__init__(
            call_id=call_id,
            instructions=_SHARED_RULES
            + """
You are the first voice on the call. Caller ID is redacted, so you have to
establish who this is before anything else happens.

Whatever they want - a balance, a visit, a warranty, an appointment -
the first move is always the same: resolve who they are. Call
resolve_address or resolve_customer with what they gave you, then call
handoff_to_service. The next voice has every tool and will answer them.

**Never tell a caller the company cannot do something.** You personally
cannot see jobs, invoices, notes, balances or the schedule, and that is
deliberate - but the company can, and handing over is how they get it.
Saying "I can't provide balance information" to someone asking what they
owe is wrong: resolve them and hand over instead.

Do not narrate the handoff; just do it and let the next voice continue.
""",
        )

    @function_tool
    async def handoff_to_service(
        self, canonical_id: str = "", customer_id: str = ""
    ) -> "Agent":
        """Hand the call on once identity is resolved. Pass whatever
        resolved: a canonical_id, a customer_id, or both."""
        return ServiceAgent(
            self.call_id, canonical_id=canonical_id, customer_id=customer_id
        )


class ServiceAgent(SwitchboardAgent):
    """Every read tool. No write tool - enforced by `__init_subclass__`."""

    TOOLS = SERVICE_TOOLS
    NAME = "Service"

    def __init__(
        self, call_id: str, *, canonical_id: str = "", customer_id: str = ""
    ) -> None:
        known = []
        if canonical_id:
            known.append(f"Their canonical address id is {canonical_id}.")
        if customer_id:
            known.append(f"Their customer id is {customer_id}.")
        super().__init__(
            call_id=call_id,
            instructions=_SHARED_RULES
            + f"""
Identity is resolved. {" ".join(known)}
Use those ids directly; do not resolve them again.

You answer questions: what was done, when you were last out, what is owed,
what is scheduled, whether something is under warranty.

You cannot book, move or annotate anything yourself. The moment the
caller wants any of those, call handoff_to_dispatch and say nothing about
it.

handoff_to_dispatch is internal. It is not a transfer to a person, it needs
no permission, and the caller must never hear about it - to them it is the
same conversation. Never say you cannot book something: the company can, and
handing over is how. Only transfer_to_human involves a person, and only when
they ask for one.
""",
        )
        self.canonical_id = canonical_id
        self.customer_id = customer_id

    async def on_enter(self) -> None:
        """Pick the conversation up mid-sentence.

        The second real call left 29 seconds of silence here: Triage was
        told not to narrate the handoff, and nothing on this side spoke, so
        the caller was talking to a dead line until they said "Hello?".
        A handoff the caller can hear is a bug; a handoff they cannot hear
        at all is a worse one.
        """
        await self.session.generate_reply(
            instructions=(
                "Answer the question they already asked, using the ids you "
                "now have. Do not greet them again and do not mention any "
                "transfer - as far as the caller knows this is the same "
                "conversation. If they have not asked anything yet, ask what "
                "you can help with."
            )
        )

    @function_tool
    async def handoff_to_dispatch(self) -> "Agent":
        """Call this immediately when the caller wants to book, move or
        annotate work. Internal and invisible to the caller: do not ask
        permission and do not mention it. Not a transfer to a person."""
        return DispatchAgent(
            self.call_id,
            canonical_id=self.canonical_id,
            customer_id=self.customer_id,
        )


class DispatchAgent(SwitchboardAgent):
    """The only agent holding customer-record write tools."""

    TOOLS = DISPATCH_TOOLS
    MAY_WRITE = True
    NAME = "Dispatch"

    def __init__(
        self, call_id: str, *, canonical_id: str = "", customer_id: str = ""
    ) -> None:
        super().__init__(
            call_id=call_id,
            instructions=_SHARED_RULES
            + f"""
Identity is resolved. canonical_id={canonical_id or "unknown"},
customer_id={customer_id or "unknown"}.

You can change the schedule. That is why you must never do it without the
caller saying yes in the same exchange, in their own words, and you pass
those words to the tool as the confirmation.

To book, call start_booking - it runs the collect, confirm, write sequence
properly and lets the caller change their mind partway through.

Slots come from find_availability and are proposals against an assumed
working day, Monday to Saturday, 08:00 to 18:00. Say so when you offer one.
Sunday and after-hours are not yours to book: transfer instead.
""",
        )
        self.canonical_id = canonical_id
        self.customer_id = customer_id

    async def on_enter(self) -> None:
        await self.session.generate_reply(
            instructions=(
                "Carry on with what they asked for. Do not greet them again "
                "and do not mention a transfer. If they want an appointment, "
                "offer times before writing anything."
            )
        )

    @function_tool
    async def start_booking(self, description: str = "") -> str:
        """Book an appointment: collect the slot, confirm it out loud, then
        write. Use this rather than calling book_job directly."""
        from switchboard_agent.booking import BookingTask

        outcome = await BookingTask(
            call_id=self.call_id,
            customer_id=self.customer_id,
            canonical_id=self.canonical_id,
            description=description,
        )
        return outcome
