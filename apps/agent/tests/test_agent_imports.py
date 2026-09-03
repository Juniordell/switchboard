"""The agent package resolves packages/core through the workspace."""

import switchboard_core
from switchboard_agent import main


def test_agent_entrypoint_is_callable() -> None:
    assert callable(main.main)


def test_agent_sees_the_core_library() -> None:
    assert main.switchboard_core is switchboard_core
