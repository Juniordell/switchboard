"""Health endpoint.

Calls the route function directly rather than going over HTTP: FastAPI's
TestClient needs httpx, which is not a dependency yet. An HTTP-level test
arrives with the real endpoints at T3.5.
"""

import switchboard_core
from switchboard_api.main import health


def test_health_reports_ok() -> None:
    result = health()
    assert result.status == "ok"


def test_health_reports_the_core_version() -> None:
    result = health()
    assert result.core_version == switchboard_core.__version__
