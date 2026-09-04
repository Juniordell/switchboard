# Build context is the repository root, because apps/api depends on
# packages/core through the uv workspace:
#
#     docker build -f apps/api/Dockerfile .
#
# This image is the whole dashboard: FastAPI under /api, and the built
# frontend on every other path. One service, one origin, no CORS.
#
FROM node:22.12.0-slim AS web

WORKDIR /web
# package files first, so editing a component does not reinstall the tree
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
# `npm run build` runs `tsc -b` first, so a type error fails the deploy
# rather than shipping. CI does not do this yet; this does.
RUN npm run build

FROM astral/uv:0.12.9-python3.12-trixie-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Manifests and lock first, so editing source does not re-resolve dependencies.
# Every workspace member's manifest is copied, including the ones this image
# does not build: uv compares the workspace against uv.lock, and a missing
# member makes the lock look stale under --locked.
COPY pyproject.toml uv.lock ./
COPY packages/core/pyproject.toml packages/core/
COPY apps/api/pyproject.toml apps/api/
COPY apps/agent/pyproject.toml apps/agent/
RUN uv sync --locked --no-dev --package switchboard-api --no-install-workspace

COPY packages/core packages/core
COPY apps/api apps/api
RUN uv sync --locked --no-dev --package switchboard-api

FROM python:3.12.14-slim-trixie AS runtime

RUN useradd --create-home --uid 1000 switchboard
WORKDIR /app

COPY --from=builder --chown=switchboard:switchboard /app /app
# main.py serves this when it exists, and works without it when it does not.
COPY --from=web --chown=switchboard:switchboard /web/dist /app/apps/web/dist

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER switchboard
EXPOSE 8000

CMD ["uvicorn", "switchboard_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
