<!-- Brief, focused instructions for AI coding agents working on TeamOps -->
# TeamOps — AI agent working notes

These notes are for AI coding agents (Copilot/Coding assistants) to get productive quickly.
Keep suggestions specific, conservative, and code-focused — implement small, testable changes and reference the files below.

1) Big-picture
- Backend: FastAPI app in `backend/app/main.py`. It exposes the Money Bots UI at `/ui/ai-content` and runs an async schedule dispatcher `AIScheduleDispatcher` from `backend/app/scheduler.py` on startup.
- Publishers: publisher adapters live in `backend/app/publishers/` (modules: `reddit.py`, `twitter.py`, `youtube.py`) and are referenced by `publishers.get_publisher()` from the backend. They read credentials via `publishers.get_env()` which falls back to `.env.production` at the repository root.
- Data: The backend uses PostgreSQL via SQLAlchemy (`DATABASE_URL` env). Schemas are created inline in `main.py` during startup (see `init_db()`). AI content tables: `ai_content_profiles`, `ai_content_jobs`, `ai_content_schedules`.

2) Critical runtime & developer workflows
- Run locally in Docker Compose (top-level `docker-compose.yml`). Deployment is automated via `scripts/deploy_vm_192_168_1_22.sh` and documented in `README.md` and `docs/deploy_vm_192.168.1.22.md`.
- Environment: set `DATABASE_URL` and `BACKEND_SECRET` at minimum. AI features require `AI_API_KEY` and optionally `AI_MODEL`/`AI_API_BASE` (default: OpenAI endpoints) defined in the environment or `.env.production`.
- Quick dev start (what's discoverable): build the backend Dockerfile in `backend/Dockerfile` and bring up services with `docker-compose up --build` from repo root. If you need to replicate production env, create `.env.production` at repo root with publisher credentials and AI keys.

3) Project-specific conventions
- Small, optimistic codebase: changes should be minimal and follow existing patterns: procedural DB access with raw SQL via SQLAlchemy engine (`engine.begin()` and `text()`), not ORM models.
- Templates: Jinja2 templates are in `backend/app/templates/`. Use `render()` in `main.py` for HTML responses.
- Sessions: lightweight signed sessions via HMAC in `main.py` (see `sign_session()` / `verify_session()`). Prefer using these helpers rather than adding new auth mechanisms.
- AI calls: centralized in `main.py` via `ai_call(messages)`. If adding generation logic, use `build_ai_messages(...)` to construct messages and keep temperature/timeout usage consistent.
- Scheduling: dispatcher polls DB and moves schedules from `scheduled` -> `queued` (see `AIScheduleDispatcher._process_due`). The code has been reconciled to use the canonical `ai_content_schedules` table and the `scheduled_for` column.

4) Integration points & external dependencies
- Database: PostgreSQL via `DATABASE_URL` (SQLAlchemy engine). SQL is executed directly with `text()` strings.
- AI provider: default is OpenAI-compatible endpoints; environment variables `AI_API_KEY`, `AI_API_BASE`, `AI_MODEL`, and `AI_TIMEOUT` control behavior. `ai_call()` uses `httpx.post`.
- Publishers: each publisher has `REQUIRED_ENV` and exposes `health_check()` and `publish(job, schedule)` — backend currently performs dry-run payload construction. Publisher credentials are loaded with `publishers.get_env()` which will read `.env.production` if present.

5) Patterns and gotchas (examples)
- Publisher env fallback: credentials read from env first, then `.env.production` via `backend/app/publishers/__init__.py::_load_env_file()` — tests or local runs may need that file created.
- DB schema vs code: Historically there was a mismatch (`ai_content_schedule` vs `ai_content_schedules`) — this has been fixed; prefer `ai_content_schedules` and `scheduled_for` when adding SQL.
- AI timezones: schedule times are parsed with `parse_schedule_time()` in `main.py` which normalizes to UTC (naive datetime) — keep timezone handling consistent when writing tests or changing scheduling logic.

6) Small, safe PR guidance for agents
- Prefer non-breaking changes: add feature flags, new env vars, or small helpers instead of large refactors.
- When editing SQL, run the code path locally in a container against a test Postgres to confirm migrations are OK.
- If adding automated publishing flows, keep existing dry-run behavior and make live publishes opt-in via env flags (e.g., `PUBLISHER_X_ENABLED=true`) and explicit credential checks.

7) Key files to inspect when working on a task
- `backend/app/main.py` — primary API, DB bootstrap, AI call helpers, message builders.
- `backend/app/scheduler.py` — polling dispatcher and queueing logic.
- `backend/app/publishers/*.py` — publisher adapters and expected `publish(job,schedule)` contract.
- `backend/Dockerfile`, `docker-compose.yml`, `scripts/deploy_vm_192_168_1_22.sh`, `README.md` — deployment and run instructions.

If anything in this doc is unclear or you need runtime-specific commands (for example exact docker-compose invocation or container names), tell me which workflow you want to validate and I'll add the explicit commands and a minimal local smoke test.
