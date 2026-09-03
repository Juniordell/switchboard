"""Application entrypoint.

Tool endpoints arrive at T3.5 and the platform endpoints at T6.1. What exists
now is a health check, so that the image, the compose service and the
dependency on packages/core are all real rather than asserted.
"""

from fastapi import FastAPI
from pydantic import BaseModel

import switchboard_core

app = FastAPI(title="Switchboard API", version=switchboard_core.__version__)


class Health(BaseModel):
    status: str
    core_version: str


@app.get("/health")
def health() -> Health:
    return Health(status="ok", core_version=switchboard_core.__version__)
