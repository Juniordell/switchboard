# Deploy runbook

Every command in order, from an empty machine to a phone number that a
person can call. Run them from the repository root unless a step says
otherwise.

The `lk` invocations were read off `lk <cmd> --help` on **v2.18.5**. Two
shapes are easy to get wrong and are correct below: the JSON request is a
positional argument rather than a flag, and `dispatch delete` takes the id
positionally while `dispatch update` takes it as `--id`. Check your own
version before blaming the runbook.

Nothing here is idempotent by accident: steps 2–5 can be re-run safely,
step 6 is the only one that changes state outside this machine, and step 9
is the one that has actually gone wrong in practice.

Environment: WSL2 (Ubuntu 24.04) on Windows, Docker via Docker Desktop's
WSL integration. Anything that must be reachable from the Windows browser
binds `0.0.0.0` — that is why the Vite script does, and it is not
decoration.

---

## 1. Secrets

```bash
cp .env.example .env
```

Fill these in. The agent will not start without the first three, and the
call will connect to silence without `OPENAI_API_KEY`.

| Key | Needed for | Without it |
|---|---|---|
| `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | the agent and every `lk` command | the worker cannot register |
| `OPENAI_API_KEY` | the LLM, the embeddings, Layer 1 | the call connects and says nothing |
| `TAVILY_API_KEY` | `web_search` | that one tool returns an error result; the rest of the call is fine |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` | tracing | spans are recorded and dropped; nothing else changes |

`DATABASE_URL` and the two port variables have working defaults in
`.env.example`. Leave them unless something else on the machine already
holds 5432 or 8000.

Never commit this file (CLAUDE.md hard rule: no `.env`, no `data/`).

## 2. Dependencies

```bash
uv sync --all-packages --locked
```

`--all-packages` is required. The workspace root is `package = false`, and
a plain `uv sync` **uninstalls the workspace members** — the failure looks
like `ModuleNotFoundError: switchboard_core` from a tree that obviously
contains it.

## 3. Postgres

```bash
docker compose up -d db
docker compose exec db pg_isready -U postgres
```

Wait for `accepting connections`. The container runs the SQL in
`infra/postgres/initdb/` on first boot only — that is where `vector` and
`pg_trgm` are created. If you ever see `operator class "gin_trgm_ops" does
not exist`, the volume predates that file:

```bash
docker compose down -v && docker compose up -d db   # destroys the database
```

## 4. Schema

```bash
cd packages/core && uv run alembic upgrade head && cd -
```

`alembic.ini` lives in `packages/core`, so this must run from there. Check:

```bash
docker compose exec db psql -U postgres -d switchboard \
  -c "SELECT nspname FROM pg_namespace WHERE nspname IN ('source','knowledge','prose','ops')"
```

Four rows. Fewer means a migration was skipped.

## 5. Data

```bash
uv run python -m switchboard_core.load
uv run python scripts/verify_load.py
```

`verify_load.py` must print **all 21 checks passed**. It compares row
counts and shapes against `docs/DATA.md`; a failure here means the load is
wrong, and every number the agent speaks afterwards is wrong with it.

Embeddings are deliberately a separate command, because this one costs
money and calls a live API:

```bash
uv run python -m switchboard_core.prose
```

It only fills rows that have no embedding yet, so re-running it after a
reload is cheap. `search_notes` returns nothing useful until it has run.

## 6. API and dashboard

```bash
uv run uvicorn switchboard_api.main:app --host 0.0.0.0 --port 8000
```

In a second shell:

```bash
cd apps/web && npm install && npm run dev
```

Vite serves on `0.0.0.0:5173`; open it from Windows at the WSL2 IP
(`hostname -I | awk '{print $1}'`). `npm run build` runs `tsc -b` first and
is the only thing that type-checks the frontend — CI does not, which is a
known gap.

If you would rather run the API in Docker:

```bash
docker compose build api && docker compose up -d api
```

**Rebuild it every time.** `docker compose up -d api` alone will happily
serve a stale image; that has already cost an afternoon here once.

## 7. Async worker

```bash
uv run python -m switchboard_api.async_agents.worker
```

Extraction and review after a call ends. The call itself works without it;
the review queue simply never fills.

## 8. The agent

```bash
uv run python -m switchboard_agent.main dev
```

`dev` reloads on edit and is what you want while iterating. For a run that
should stay up:

```bash
uv run python -m switchboard_agent.main start
```

Either way, the log line to look for names the agent:

```
registered worker  ... agent_name="switchboard"
```

That string comes from `@server.rtc_session(agent_name="switchboard")` in
`apps/agent/src/switchboard_agent/main.py`. Step 9 is entirely about it.

## 9. Point the phone number at the agent

Inspect what exists before changing anything:

```bash
lk sip inbound list
lk sip dispatch list
```

If there is no rule yet, create one. The room prefix matters: the agent
reads the caller's number back out of the room name, so `call-` is not
cosmetic.

```bash
lk sip dispatch create - <<'JSON'
{
  "name": "switchboard-inbound",
  "trunk_ids": ["<ST_... from `lk sip inbound list`>"],
  "rule": { "dispatchRuleIndividual": { "roomPrefix": "call-" } },
  "room_config": {
    "agents": [{ "agent_name": "switchboard" }]
  }
}
JSON
```

Then call the number. You should see the worker log a job and the room
appear in `lk room list`.

---

### When the dispatch rule points at the wrong agent name

**The symptom is silence, not an error.** The call connects, the room is
created, the caller hears nothing and eventually hangs up. LiveKit
dispatches to a name; if no worker is registered under that name, nothing
joins and nothing complains. Every log you are inclined to check — the
agent's, the API's — is quiet, because neither was ever involved.

Confirm it is this, and not something else, by comparing the two sides:

```bash
# what the rule asks for
lk sip dispatch list --json | grep -i agentname

# what the worker registered as
grep -rn 'agent_name=' apps/agent/src/switchboard_agent/main.py
```

If those two strings differ, this is your problem. If they match, it is
not — go look at whether the worker is actually running and whether
`LIVEKIT_URL` in `.env` points at the same project the rule lives in.

**`lk sip dispatch update` has no flag for the agent name.** Checked
against `lk sip dispatch update --help` on v2.18.5: it offers `--name`,
`--trunks`, `--direct`, `--caller`, `--callee`, and nothing for the agent.
The name lives inside `room_config.agents[]`, so the fix goes through JSON.

Take the current rule as your template rather than retyping it, so you
keep the trunk ids and the room prefix exactly as they are:

```bash
lk sip dispatch list --json > /tmp/rule.json
```

Edit `/tmp/rule.json`: keep one rule object, set the agent name to
`switchboard`, and keep the rule's id. Field spelling follows whatever
`list --json` printed — the API accepts both `agent_name` and `agentName`,
so copy the casing you were given rather than the casing in this document.
Then:

```bash
lk sip dispatch update --id <SDR_...> /tmp/rule.json
lk sip dispatch list          # confirm before you dial
```

If `update` argues about the request shape, delete and recreate. It is two
commands and there is no state worth preserving in a dispatch rule:

```bash
lk sip dispatch delete <SDR_...>
# then the create from step 9
```

**Do not fix this by renaming the agent in the code to match the rule.**
The name is referenced by the eval harness and by `docs/ARCHITECTURE.md`;
the rule is the thing that is wrong, and it is the cheaper of the two to
change. If you genuinely need a different name — running two agents
against one project, say — change `main.py` *and* the rule together, in
one commit, and say why.

## 10. Verify end to end

```bash
bash scripts/smoke_tools.sh                        # every tool, over HTTP
uv run python scripts/measure_event_latency.py     # tool call -> SSE frame
```

The second needs the API from step 6 already running, and asserts the T6.2
requirement: a tool call reaches the dashboard in under a second. Measured
here at p50 10.7 ms, p95 12.6 ms, max 45.0 ms.

Then make a real call and watch it land in the dashboard's call log.

## Rollback

```bash
docker compose down                 # keeps the data volume
docker compose down -v              # destroys it; steps 4-5 again afterwards
cd packages/core && uv run alembic downgrade -1 && cd -
```

The dispatch rule is the only thing that outlives the machine. If you are
handing the number back, delete it:

```bash
lk sip dispatch delete <SDR_...>
```
