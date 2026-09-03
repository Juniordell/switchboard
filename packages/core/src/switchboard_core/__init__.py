"""Switchboard domain library.

Records, derived knowledge and the tool implementations that read them. The
voice agent binds these tools, the FastAPI app exposes them and the async
agents import them: one implementation, three callers.

This package depends on no web or voice framework, deliberately. apps/api and
apps/agent import switchboard_core; nothing here imports them back. The rule is
enforced by a test rather than remembered - see tests/test_core_imports.py.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
