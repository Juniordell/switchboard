"""The domain errors T3.1 deferred.

`tool_call` returns a typed `ToolError` for a `ToolDomainError` and lets
everything else propagate, which left Phase 2's bare `ValueError`s on the
wrong side of that line. Each tool that wraps one of those functions
translates at its own boundary, into one of the types here - the knowledge
and prose layers keep raising what they raise, since they are also called
directly by build steps and scripts that want the traceback.

What belongs here is an outcome a caller can cause or a condition the tool
cannot answer through. A defect stays a defect: nothing in this module is
raised for a bug.
"""

from switchboard_core.tools.contract import ToolDomainError


class InvalidEntityIdError(ToolDomainError):
    """An entity id in the wrong shape - not a `cadr_...` or a `job_...`, or
    empty. The caller (an agent, mid-call) supplied it, so it is a domain
    outcome rather than a defect: `search_notes` is unusable without a
    resolved scope, and CLAUDE.md hard rule 3 makes that structural.
    """


class RetrievalUnavailableError(ToolDomainError):
    """The embedding API could not be reached, or is not configured.

    Not a defect in the calling path and not something a retry inside the
    tool would fix. On a live call the correct behaviour is to say the notes
    cannot be searched right now and offer a human, which needs a returned
    result rather than a traceback - the failure is still loud in the call
    log as `ok: false`, and still fails a test that asserts a real search.
    """


class JobNotFoundError(ToolDomainError):
    """No job with that id, in `source.jobs` or in the write overlay.

    A caller-supplied id that resolves to nothing is a domain outcome: the
    agent misheard a number, or the job belongs to a different customer.
    Not a defect, and not something to write against blindly.
    """
