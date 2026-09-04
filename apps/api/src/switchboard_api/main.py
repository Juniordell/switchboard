"""Application entrypoint.

One service, one origin. The API answers under `/api`; everything else is
the built frontend. That is why there is no CORS configuration anywhere in
this repo - the browser only ever talks to the origin it was served from.

Every tool is exposed by `switchboard_api.tools` (T3.5); the operations
platform - calls, tool_calls, jobs, review_queue and the live event stream
- by `switchboard_api.platform` (T6.1, T6.2).
"""

import logging
import os
import pathlib

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import switchboard_core
from switchboard_api import platform, tools

logger = logging.getLogger(__name__)

#: The Vite build. Present in the image, usually absent in a checkout that
#: has not run `npm run build` - so serving it is conditional, and the API
#: is fully usable without it.
#:
#: `SWITCHBOARD_WEB_DIST` wins, because the path below is derived from this
#: file's location and that depends on how the package was installed. In a
#: container it is worth stating outright rather than inferring.
WEB_DIST = pathlib.Path(
    os.environ.get("SWITCHBOARD_WEB_DIST")
    or pathlib.Path(__file__).resolve().parents[4] / "apps" / "web" / "dist"
)

app = FastAPI(title="Switchboard API", version=switchboard_core.__version__)

#: `/api` is the real prefix, not a dev-server fiction. The Vite proxy
#: forwards `/api` untouched, so a path is the same string in development,
#: in the tests and in production.
app.include_router(tools.router, prefix="/api")
app.include_router(platform.router, prefix="/api")


class Health(BaseModel):
    status: str
    core_version: str


@app.get("/health")
def health() -> Health:
    """Unprefixed: this is for the platform's health check, not the app."""
    return Health(status="ok", core_version=switchboard_core.__version__)


def _mount_frontend(dist: pathlib.Path) -> None:
    """Serve the built dashboard, with a fallback to index.html.

    The fallback is what makes a deep link work: the router is client-side,
    so `/calls/abc` is a path the server has never heard of and must still
    answer with the app rather than a 404.
    """
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        candidate = dist / path
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")


if (WEB_DIST / "index.html").is_file():
    _mount_frontend(WEB_DIST)
    logger.info("serving the dashboard from %s", WEB_DIST)
else:
    # Not fatal - the API is the product, the dashboard is a client of it -
    # but in a deployment this means someone gets a 404 instead of a page,
    # so it should be loud.
    logger.warning("no frontend build at %s; serving the API only", WEB_DIST)
