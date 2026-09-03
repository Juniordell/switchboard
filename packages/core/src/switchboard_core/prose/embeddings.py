"""Calling OpenAI's `/v1/embeddings` for `text-embedding-3-small`.

`httpx`, not the `openai` SDK - see `docs/DECISIONS.md` for why. `httpx` was
also the specific dependency approved for this task (T2.5), not a general
"add an HTTP client" decision.

Synchronous, matching the rest of `switchboard_core`: nothing else in this
codebase is async, and this call sits behind `search_notes`, which the voice
agent calls from a synchronous tool-call context.
"""

import os

import httpx

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"

#: OpenAI accepts up to ~2048 inputs per request; kept well under that so a
#: failure partway through a bulk embedding run loses at most one batch's
#: worth of API cost, not the whole run's.
BATCH_SIZE = 100


class EmbeddingsError(RuntimeError):
    """OPENAI_API_KEY is not set, or the API call itself failed."""


def _api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise EmbeddingsError(
            "OPENAI_API_KEY is not set - cannot call the embeddings API"
        )
    return key


def embed_texts(
    texts: list[str], *, client: httpx.Client | None = None
) -> list[list[float]]:
    """One embedding vector per input text, in the same order as `texts`.

    `texts` must already respect `BATCH_SIZE` - this function makes exactly
    one API call, it does not chunk a large list itself. Callers that embed
    more than `BATCH_SIZE` texts are responsible for batching (see
    `embed_pending.py`), so that a failure is scoped to one batch.
    """
    if not texts:
        return []

    owns_client = client is None
    http_client = client or httpx.Client(timeout=30.0)
    try:
        response = http_client.post(
            EMBEDDINGS_URL,
            headers={"Authorization": f"Bearer {_api_key()}"},
            json={"model": EMBEDDING_MODEL, "input": texts},
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise EmbeddingsError(
                f"embeddings API returned {exc.response.status_code}: "
                f"{exc.response.text[:500]}"
            ) from exc

        payload = response.json()
        # The API documents in-order results, indexed 0..n-1 - sorted
        # explicitly rather than trusted, since silently misaligning a
        # vector with the wrong note is worse than a redundant sort.
        ordered = sorted(payload["data"], key=lambda item: item["index"])
        if len(ordered) != len(texts):
            raise EmbeddingsError(
                f"expected {len(texts)} embeddings, got {len(ordered)}"
            )
        return [item["embedding"] for item in ordered]
    finally:
        if owns_client:
            http_client.close()
