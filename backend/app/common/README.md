# `backend/app/common/` — Cross-cutting plumbing

This directory holds the pieces every router relies on but no single feature owns:
- authentication and authorization dependencies
- the application's error types and how they become HTTP responses
- logging setup
- rate limiting
- safe upload reading

[`__init__.py`](__init__.py) is empty; import from each module directly.

**Dependency direction:** despite the name, `common` is not the bottom layer. `dependencies.py` imports `decode_token` and `get_user_by_id` from [`services/auth_service.py`](../services/auth_service.py), and the models directly. The other modules depend only on FastAPI/third-party code and [`../config.py`](../config.py).

## Files

| File | What it provides | Wired in by |
|---|---|---|
| [`dependencies.py`](dependencies.py) | FastAPI `Depends(...)` functions: `get_current_user`, `require_admin`, `get_refresh_token`, `require_course_member`, `require_course_staff`, and the `CourseMember` result type | Each router's endpoint signatures |
| [`exceptions.py`](exceptions.py) | `QnaError` and its subclasses, plus `register_exception_handlers(app)` | `main.py` |
| [`logging.py`](logging.py) | `configure_logging()` for structlog | `main.py` (at import time) |
| [`rate_limit.py`](rate_limit.py) | The shared slowapi `limiter` | `main.py` (`app.state.limiter`, `SlowAPIMiddleware`) and `@limiter.limit(...)` in `routers/auth.py` |
| [`uploads.py`](uploads.py) | `read_upload_capped(file, max_bytes=2 MB)` | `routers/admin.py` roster and staff CSV uploads |

## Authentication: `get_current_user`

1. **`_token_from_request`** takes the JWT from the `Authorization: Bearer …` header, falling back to an `access_token` cookie. The backend never sets that cookie itself; the frontends send the Bearer header.
2. **The token is decoded** with the RS256 public key via `auth_service.decode_token`. Bad signature or expiry → `401 UNAUTHORIZED`.
3. **`token_type` must be `access` or `temp`.** A short-lived `temp` token (issued by the SSO callback and the dev netid login) is accepted by every authenticated endpoint, not only `/auth/exchange-temp`. A `refresh` token is rejected.
4. **The `User` row is loaded** from the token's `sub`. A missing user → `401`.

`require_admin` then checks `user.role == "ADMIN"` → otherwise `403 FORBIDDEN`.

## Course-scoped authorization: `require_course_member` / `require_course_staff`

This is how the board enforces "access is granted per user, per course". `course_id` comes from the **path parameter** of the endpoint the dependency is attached to.

```
require_course_member(course_id, user, db, X-App-Surface header)
  if user.role == ADMIN:                natural_role = STAFF     (no access row needed, course existence not checked)
  else: look up UserCourseAccess(user, course)
        no row  -> 404 "Course {id} not found"                     (not 403: doesn't reveal the course exists)
        row     -> natural_role = row.role (STUDENT | STAFF)
  effective_role = STUDENT if X-App-Surface == "student" else natural_role
  return CourseMember(user, effective_role)

require_course_staff(member) -> 403 unless member.course_role == STAFF
```

**`X-App-Surface` can only lower capability, never raise it.** The student app sends `X-App-Surface: student` on every request (`frontend/student/src/lib/api.ts`), so a staff member or admin using the student app is treated exactly like a student. Their posts are also recorded with `author_role="STUDENT"`, because `routers/qa.py:create_post` passes `member.course_role` into the post. Only the value `student` has any effect. The staff app sends `staff`; the admin app and scripts such as `eval/compare_harness.py` send nothing. All of these get the account's natural role.

## Errors: `exceptions.py`

All application errors are raised as `QnaError(code, message, status_code)` subclasses and turned into one JSON shape.

| Class | Status | `error` code |
|---|---|---|
| `QnaError` (base, default) | 400 | whatever is passed |
| `NotFoundError` | 404 | `NOT_FOUND` |
| `ForbiddenError` | 403 | `FORBIDDEN` |
| `UnauthorizedError` | 401 | `UNAUTHORIZED` |
| `ConflictError` | 409 | `CONFLICT` |
| `PayloadTooLargeError` | 413 | `PAYLOAD_TOO_LARGE` |

`register_exception_handlers` installs three handlers:

| Raised | Status | Response body |
|---|---|---|
| `QnaError` | its `status_code` | `{"error": code, "message": message}` (logged as `app_error`) |
| Pydantic `RequestValidationError` | 422 | `{"error": "VALIDATION_ERROR", "detail": [...]}` (run through `jsonable_encoder`; see the `LoginRequest` note in [`../schemas/README.md`](../schemas/README.md)) |
| Anything else | 500 | `{"error": "INTERNAL_ERROR", ...}` (stack trace logged, not returned) |

Rate-limit violations are the one exception. They return a 429 from slowapi's own handler (registered in `main.py`), not this module's JSON shape.

## Logging: `logging.py`

structlog is configured once at import time in `main.py`.

| | Development (`APP_ENV=development`) | Otherwise |
|---|---|---|
| Output | Colored console | One JSON object per line |
| Level | `DEBUG` | `INFO` |
| `uvicorn.access` | Default | Lowered to `WARNING` |

Convention used everywhere: `logger = structlog.get_logger()` at module top, then a snake_case event name plus keyword context, e.g. `logger.info("post_created", question_id=..., post_id=...)`.

## Rate limiting: `rate_limit.py`

- **Only two endpoints are limited:** `POST /api/auth/login` (`5/15minutes`) and `POST /api/auth/exchange-temp` (`10/minute`). A limited endpoint must take `request: Request` in its signature for slowapi to work.
- **In development the key is a fresh UUID per request**, so limits never fire locally.
- **In production the key is the client address nginx forwards**, `X-Real-IP`, falling back to the socket peer if the header is missing. The peer itself is always nginx, so keying on it would put every user in one bucket.
  - `nginx/nginx.prod.conf` sends `X-Real-IP $remote_addr` with `proxy_set_header`, which replaces any value the client sent, so the header can't be spoofed through nginx.
  - Worth knowing for deployment, because the eval harness and the team all log in through `/api/auth/login`.
- **Counters live in Redis in production** (`storage_uri=settings.REDIS_URL`), so they're shared and survive restarts and redeploys. If Redis is unreachable, `in_memory_fallback_enabled` falls back to per-process memory rather than failing logins. Development uses `memory://`, since its keys are random anyway.

### Fixed: one shared login limit in production

**Was:** the key was nginx's address and the counters were per process, so after about 5 logins in 15 minutes from *anyone*, every further login on the deployed app got a 429, `eval/compare_harness.py` included. Fixed on `fix/rate-limit-client-ip` as described above.

**Why not uvicorn's `--forwarded-allow-ips='*'`:** nginx uses `$proxy_add_x_forwarded_for`, which *appends* the real address to whatever `X-Forwarded-For` the client sent. Depending on the uvicorn version, trusting `*` can make the left-most, client-written entry win. A client could then send a fresh fake address on every request and never be limited.

**Precondition:** the backend must be reachable **only** through nginx in production, or `X-Real-IP` could be forged by calling the backend directly. The deployment guide's `docker-compose.prod.yml` publishes only nginx's port 80, and the VM firewall allows only HTTP/HTTPS. Keep it that way: don't publish port 8000 on the VM.

**How to verify:**
- **On the VM:** make 6 wrong-password logins from one network and confirm the 6th returns 429. Then log in from a different network (e.g. phone on mobile data); it must still succeed. After a redeploy, the first network should still be limited until its 15 minutes are up.
- **Locally:** limits are disabled in development, so the local checks are the unit tests in `tests/unit/test_rate_limit.py`, which call `_rate_limit_key` with fake requests carrying `X-Real-IP`.

## Uploads: `uploads.py`

`read_upload_capped` reads an `UploadFile` in 64 KB chunks and raises `PayloadTooLargeError` (413) once the total passes `max_bytes` (default 2 MB). It exists because Starlette doesn't limit upload size, and `Content-Length` can't be trusted (chunked uploads omit it).

## Where the RAG feature will touch this directory

Notes for the design work (T3):

- **Staff-only RAG endpoints reuse `require_course_staff`.** That covers `/rag/compare`, resource registration and re-sync. The harness logs in as an admin and sends no `X-App-Surface` header, so admins pass as `STAFF`. The access-control integration tests (T7) should cover a student, a non-member (expect 404) and an admin.
- **An "unpulled generation model" error needs a 4xx.** T6 requires it, and `QnaError` with an explicit `status_code`, or a new subclass, fits the existing error shape.
- **The 2 MB `MAX_UPLOAD_BYTES` default is sized for CSVs.** PDFs and zipped repositories for the upload fallback will need a larger, explicit `max_bytes`.
- **Redis holds only the login rate-limit counters.** That leaves it available for abuse control on AI answering, or as a queue/lock for ingestion jobs, if the design calls for one.
