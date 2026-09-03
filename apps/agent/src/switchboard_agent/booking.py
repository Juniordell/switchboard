"""Booking as a task group: collect, confirm out loud, write.

`docs/ARCHITECTURE.md` calls for exactly this shape, and the reason is the
step-back path. A caller changes their mind halfway through booking more
often than they do anything else on this kind of call - "actually, can we
make it Thursday", "hold on, let me check with my wife" - and an agent that
has already written is an agent apologising.

So the write happens once, at the end, after the slot has been said back to
the caller and they have agreed in their own words. Before that point every
piece of state lives in the task and nothing has touched the database.

`AgentTask[BookingOutcome]` rather than a chain of tool calls because the
task owns its own instructions and its own small tool set: while it is
running, `confirm` and `change_my_mind` and `give_up` are the whole world,
which is what stops the model from wandering back into general enquiry
halfway through a confirmation.
"""

import datetime
import logging

from livekit.agents import AgentTask, function_tool

from switchboard_agent.tool_bridge import call_core_tool
from switchboard_core.tools import BookJobRequest, book_job

log = logging.getLogger("switchboard_agent.booking")

INSTRUCTIONS = """You are booking one appointment, and nothing else.

The sequence, in order:
1. If you do not have a slot yet, offer the ones you were given. Say the
   window out loud - "Thursday the fourth, between ten and twelve" - and say
   it is an estimated arrival window.
2. Say the slot back and ask them to confirm in words. "Shall I book that?"
3. Only when they clearly agree, call confirm_booking and pass their exact
   words as spoken_confirmation.

If they change their mind about the time, call change_the_slot and start
again from the new one. If they want to stop, or want to think about it, or
ask for a person, call abandon_booking - stopping is a normal outcome, not
a failure, and nothing will have been written.

Never say the appointment is booked before confirm_booking has returned.
"""


class BookingOutcome:
    """What came back, in a form the Dispatch agent can speak."""

    def __init__(self, spoken: str, job_id: str | None = None) -> None:
        self.spoken = spoken
        self.job_id = job_id

    def __str__(self) -> str:
        return self.spoken


class BookingTask(AgentTask[str]):
    """Collect a slot, confirm it, write it. One write, at the end."""

    def __init__(
        self,
        *,
        call_id: str,
        customer_id: str,
        canonical_id: str,
        description: str = "",
        display_address: str = "",
    ) -> None:
        super().__init__(instructions=INSTRUCTIONS)
        self.call_id = call_id
        self.customer_id = customer_id
        self.canonical_id = canonical_id
        self.description = description or "Service call booked by phone"
        self.display_address = display_address

        #: Collected, not written. Nothing below touches the database until
        #: confirm_booking runs.
        self.slot: datetime.datetime | None = None

    async def on_enter(self) -> None:
        await self.session.generate_reply(
            instructions=(
                "Offer the caller a time, saying the window out loud and that "
                "it is an estimated arrival window."
            )
        )

    @function_tool
    async def propose_slot(self, starts_at: str) -> str:
        """Record the slot the caller is considering, in ISO 8601. Say it
        back to them afterwards and ask them to confirm."""
        try:
            self.slot = datetime.datetime.fromisoformat(starts_at)
        except ValueError:
            return "that is not a time I can read back; ask them again"
        return (
            f"holding {self.slot.isoformat()} - say the window back to them and "
            f"ask them to confirm before you book it"
        )

    @function_tool
    async def change_the_slot(self) -> str:
        """The caller changed their mind about the time. Clears the held
        slot so a new one can be proposed. Nothing has been written."""
        previous, self.slot = self.slot, None
        log.info(
            "booking slot cleared",
            extra={"call_id": self.call_id, "previous": str(previous)},
        )
        return "slot cleared, nothing was written - ask them what time suits"

    @function_tool
    async def confirm_booking(self, spoken_confirmation: str) -> str:
        """Write the booking. Only after the caller has agreed out loud, and
        `spoken_confirmation` must be their own words."""
        if self.slot is None:
            return "no slot is held yet - propose one and confirm it first"

        if not spoken_confirmation.strip():
            return (
                "the caller has not agreed in words yet - ask them to confirm "
                "before this can be written"
            )

        outcome = call_core_tool(
            book_job,
            BookJobRequest(
                customer_id=self.customer_id,
                scheduled_start=self.slot,
                description=self.description,
                display_address=self.display_address or self.canonical_id,
                canonical_id=self.canonical_id or None,
                spoken_confirmation=spoken_confirmation,
            ),
            call_id=self.call_id,
            handled_by="Dispatch",
        )

        if getattr(outcome, "job_id", None) is None:
            self.complete("I could not get that booked. Let me pass you to someone.")
            return "the booking failed; tell them and offer a person"

        when = self.slot.strftime("%A the %d, at %H:%M")
        self.complete(f"Booked for {when}.")
        return f"booked: {outcome.job_id}. Tell them it is confirmed for {when}."

    @function_tool
    async def abandon_booking(self, why: str = "") -> str:
        """The caller wants to stop, think about it, or speak to a person.
        Nothing is written. This is a normal ending."""
        log.info("booking abandoned", extra={"call_id": self.call_id, "why": why})
        self.complete("Nothing was booked.")
        return "stopped without writing anything - carry on with the call"
