"""Application entrypoint.

Every tool is exposed by `switchboard_api.tools` (T3.5). The platform
endpoints - calls, tool_calls, jobs, review_queue - arrive at T6.1.
"""

from fastapi import FastAPI
from pydantic import BaseModel

import switchboard_core
from switchboard_api import tools

app = FastAPI(title="Switchboard API", version=switchboard_core.__version__)
app.include_router(tools.router)


class Health(BaseModel):
    status: str
    core_version: str


@app.get("/health")
def health() -> Health:
    return Health(status="ok", core_version=switchboard_core.__version__)
