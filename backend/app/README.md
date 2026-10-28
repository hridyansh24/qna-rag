# `backend/app/` — The QnA FastAPI application

This is the whole backend: one FastAPI app (`app.main:app`) that serves the JSON API under `/api`, backed by MySQL through async SQLAlchemy. nginx sits in front of it and also serves the three React apps. This README is the roll-up of the per-directory READMEs below. Start here, then go down a level for detail.

## Layers

```
            HTTP request (/api/...)
                     │
   main.py ── middleware: SlowAPI rate limiting, CORS; exception handlers
                     │
   routers/     endpoints: path + schemas + Depends(guards) → call a service → commit
     │    │
     │    └──── common/   auth & course-access guards, error types, logging, limiter, upload cap
     │
   schemas/     Pydantic request validation / response shapes (shared with services)
     │
   services/    business rules; flush() but never commit(); return ORM objects + serialize_* dicts
     │
   models/      SQLAlchemy tables and relationships (no rules)
     │
   database.py  async engine + get_db session (commit on success, rollback on error)
                     │
                   MySQL
```

| Directory | One-line summary | Details |
|---|---|---|
| [`routers/`](routers/) | Every endpoint: `health`, `auth`, `admin` (global admin only), `qa` (the course-scoped board) | [README](routers/README.md) |
| [`services/`](services/) | Thread rules (post/accept/close), JWT and passwords, roster/staff imports, startup accounts | [README](services/README.md) |
| [`schemas/`](schemas/) | Pydantic v2 bodies. Requests forbid unknown fields; thread responses are built from `serialize_*` dicts | [README](schemas/README.md) |
| [`models/`](models/) | `users`, `courses`, `course_rosters`, `user_course_access`, `categories`, `questions`, `question_categories`, `posts` | [README](models/README.md) |
| [`common/`](common/) | `get_current_user`, `require_admin`, `require_course_member/staff` (+ `X-App-Surface` clamp), `QnaError` → JSON, structlog, slowapi, upload cap | [README](common/README.md) |
| [`migrations/`](migrations/) | Alembic. One revision so far (`001_initial_schema.py`); `env.py` imports `app.models` to find tables | — |

## Files at this level

| File | Purpose |
|---|---|
| [`main.py`](main.py) | Builds the app. Configures logging, installs the limiter and CORS middleware, registers error handlers, mounts the four routers under `/api`. Its `lifespan` connects Redis and runs `bootstrap_admin()` before serving. Swagger (`/api/docs`) is enabled only in development |
| [`config.py`](config.py) | `Settings` (pydantic-settings), read from the environment / `.env`, unknown keys ignored: `APP_ENV`, `DATABASE_URL`, `REDIS_URL`, `JWT_*_KEY`, `OAUTH2_PROXY_SHARED_SECRET`, `CORS_ORIGINS`, `FRONTEND_URL`, `ADMIN_*`. `settings.is_development` drives the dev-only behaviors (netid login, Swagger, console logs, disabled rate limits, non-`Secure` cookies) |
| [`database.py`](database.py) | Async engine (`asyncmy`), `AsyncSessionLocal`, the declarative `Base`, and `get_db`. `get_db` yields one session per request, commits if the request succeeds and rolls back if it raises |
| [`redis_client.py`](redis_client.py) | A lazily created `redis.asyncio` client, opened at startup and closed at shutdown. **Nothing else uses it yet** |

## How a request flows: a student asks a question

`POST /api/courses/7/questions` from the student app:

1. **nginx** forwards `/api/*` to the backend. **`SlowAPIMiddleware`** passes it through; this route isn't rate-limited.
2. **Dependencies.**
   - `get_db` opens a session.
   - `get_current_user` validates the Bearer JWT (RS256, `access` or `temp`) and loads the `User`.
   - `require_course_member(course_id=7)` finds the user's `UserCourseAccess` row: no row → **404**; an `ADMIN` → STAFF. Because the student app sends `X-App-Surface: student`, the effective role is clamped to `STUDENT`.
3. **Validation.** The body is checked against `schemas.qa.QuestionCreate`: an unknown field, an empty title or no categories → **422**.
4. **`qa_service.create_question`** checks the categories belong to course 7 (else **404**), inserts the `Question` and its `QuestionCategory` links, flushes, and reloads the question with every relationship eager-loaded.
5. **The router commits**, then returns `serialize_question_detail(question)`. FastAPI checks it against `QuestionDetail` and replies **201**.

Answering, accepting and closing follow the same path through `create_post`, `set_post_accepted` and `close_question`. Each write returns the full, reloaded thread. Accepting needs `require_course_staff`. A closed thread rejects new posts with **409** until staff reopen it.

**Today, nothing happens after step 5.** There is no AI step: an unanswered question just waits for a human.

## Startup sequence

`uvicorn app.main:app` imports `main.py`:
1. `configure_logging()` runs at import time.
2. In `lifespan`, Redis is connected.
3. `bootstrap_admin()` creates the first admin from `ADMIN_USERNAME`/`ADMIN_PASSWORD` if needed. On a fresh database it **blocks**, retrying every 5 seconds, until `alembic upgrade head` has created the schema.
4. Only then does the app accept requests.

## Cross-cutting facts worth remembering

- **Two role systems.** Global `User.role` (`ADMIN`/`USER`) and per-course `UserCourseAccess.role` (`STUDENT`/`STAFF`). An `ADMIN` is `STAFF` everywhere without a grant. `Post.author_role` freezes the effective role at posting time.
- **Business rules live in services, not the schema.** "One accepted answer per question", "only answers can be accepted" and "closed threads take no posts" are all enforced in `qa_service`.
- **Async all the way.** Relationships must be eager-loaded (`_question_load_options`), and blocking work must stay off the event loop.
- **Errors have one JSON shape**, `{"error": CODE, "message": ...}`, except validation (422, `detail`) and rate limits (429, slowapi's own shape).
- **Production rate limiting may be one shared bucket.** It is keyed on the peer IP, which is probably nginx's, and stored in memory (see [`common/README.md`](common/README.md)).

## Where the RAG feature plugs in (summary)

The directory READMEs each end with the constraints the current code puts on the RAG design. In one place:

| Area | Constraint |
|---|---|
| **models** | A new `Post.author_role` enum value (an `ALTER` migration), and an author for AI posts (`author_user_id` is `NOT NULL`). New tables for resources, ingestion profiles and citation metadata, each imported in `models/__init__.py` |
| **schemas** | `PostResponse` gains an AI label and citations. A new `/rag/compare` request/response must match the T6 contract exactly |
| **services** | Trigger after `create_question` commits. CPU generation is slow, so decide whether it runs inside the request or outside it (outside needs its own session). AI posts reuse `create_post`, and accepting them reuses `set_post_accepted` unchanged. Model/vector clients must not block the event loop |
| **routers** | A new staff-only router mounted in `main.py`. `/rag/compare` must never write to the board and must answer within the harness's 180 s timeout |
| **common** | Reuse `require_course_staff`. Return a 4xx `QnaError` for a generation model that isn't pulled. Raise the 2 MB upload cap for PDFs/zips |
| **config** | Service URLs (Ollama, Infinity, ChromaDB) and the GitLab access token belong in `Settings` / `.env`, never in code or CI variables |
