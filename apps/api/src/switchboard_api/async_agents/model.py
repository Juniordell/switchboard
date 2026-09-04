"""One JSON call to the model, over httpx.

Same reasoning as the embeddings client (T2.5) and the T4.0 tool client: a
single endpoint with a JSON body does not need an SDK, and httpx is already
pinned. `response_format` is what makes the answer parseable without asking
the model politely to return JSON and hoping.
"""

import json
import os
from typing import Any

import httpx
from opentelemetry import trace
from opentelemetry.semconv._incubating.attributes import gen_ai_attributes as gen_ai

from switchboard_core.telemetry import record_usage

CHAT_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = os.environ.get("ASYNC_AGENT_MODEL", "gpt-4o-mini")
REQUEST_TIMEOUT_SECONDS = 60.0


class ModelUnavailableError(RuntimeError):
    """The model could not be reached or is not configured."""


def ask_for_json(
    system: str,
    user: str,
    *,
    model: str = DEFAULT_MODEL,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Ask for a JSON object and return it parsed.

    Latency does not matter here - `docs/ARCHITECTURE.md` puts these agents
    after the caller has hung up, which is the whole point of running them
    there rather than on the call.
    """
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise ModelUnavailableError("OPENAI_API_KEY is not set")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }

    http = client or httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
    try:
        response = http.post(
            CHAT_URL, json=payload, headers={"Authorization": f"Bearer {key}"}
        )
    except httpx.HTTPError as exc:
        raise ModelUnavailableError(str(exc)) from exc
    finally:
        if client is None:
            http.close()

    if response.status_code != httpx.codes.OK:
        raise ModelUnavailableError(
            f"model returned {response.status_code}: {response.text[:200]}"
        )

    body = response.json()
    span = trace.get_current_span()
    record_usage(span, body.get("usage"))
    span.set_attribute(gen_ai.GEN_AI_RESPONSE_MODEL, body.get("model", model))

    content = body["choices"][0]["message"]["content"]
    try:
        return json.loads(content)
    except ValueError as exc:
        raise ModelUnavailableError(
            f"model did not return JSON: {content[:200]}"
        ) from exc
