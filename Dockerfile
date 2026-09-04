# Build context is the repository root, because apps/agent depends on
# packages/core through the uv workspace:
#
#     docker build -f apps/agent/Dockerfile .
#
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
RUN uv sync --locked --no-dev --package switchboard-agent --no-install-workspace

COPY packages/core packages/core
COPY apps/agent apps/agent
RUN uv sync --locked --no-dev --package switchboard-agent

FROM python:3.12.14-slim-trixie AS runtime

RUN useradd --create-home --uid 1000 switchboard
WORKDIR /app

COPY --from=builder --chown=switchboard:switchboard /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER switchboard

# `start` is not optional: cli.run_app is a subcommand CLI, and without it
# the container prints its help and exits 0 - a deploy that looks healthy
# while no worker ever registers, and a caller who hears silence.
CMD ["python", "-m", "switchboard_agent.main", "start"]
