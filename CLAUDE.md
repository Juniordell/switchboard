# Switchboard — voice front desk and operations platform

Take-home for Kebra. 48 hours. Read docs/SCOPE.md, docs/ARCHITECTURE.md,
docs/DATA.md, docs/AGENTS.md and docs/HARNESS.md before proposing anything.

## Hard rules

1. Never modify anything under data/. It is the provided dataset and the
   assignment forbids changing it. Loaders read it; nothing writes to it.
2. Facts come from SQL. Prose comes from retrieval. Never answer a question
   about dates, counts, schedules, balances or warranty with a vector search.
3. search_notes requires a resolved entity id as a positional argument. An
   unscoped semantic search over the corpus is a bug, not an option.
4. Write tools live only on the Dispatch agent. No read-path agent may import
   or expose them.
5. Every tool call is logged with call_id, agent, tool, args, duration_ms,
   result_rows and ok. Including failures.
6. No new dependency without asking. Specifically: no LangChain, no MLflow, no
   vector database, no reranker. If you think one is needed, say why and stop.
7. Pin every version exactly. No carets, no tildes, no unpinned installs.

## Stack

Runs on WSL2 (Ubuntu 24.04) on Windows. Docker via Docker Desktop WSL integration.
Python 3.12, uv workspace: apps/agent, apps/api, apps/web, packages/core.
FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic.
Postgres 17 with pgvector and pg_trgm.
LiveKit Agents (AgentServer + @server.rtc_session), LiveKit Inference, cascade.
Vite + React 19 + TypeScript + Tailwind + TanStack Query.
Langfuse over OpenTelemetry.

## Working style

- One task at a time from docs/TASKS.md. Do not skip ahead.
- Before writing code, restate the task and list the files you will touch.
  Wait for confirmation.
- After each task: ruff check, pytest, then stop and report.
- Commit yourself after every logical unit, not at the end of a task. A unit is
  one loader, one derived table, one tool, one screen. If a diff is over ~150
  lines it was more than one unit.
- Conventional commits. Types: feat, fix, chore, docs, test, refactor, ci, build.
  Scopes, closed list: core, agent, api, web, infra, evals, data, repo.
  Subject line under 72 chars, imperative, lowercase, no trailing period.
- Never mix two scopes in one commit. If you did, it was two commits.
- Never commit .env or data/. Never commit to main; we work on phase branches.
- If a spec is wrong or ambiguous, say so instead of guessing.
- Prefer boring, readable code. This repo is read by a reviewer.
