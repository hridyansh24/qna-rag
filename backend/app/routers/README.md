# `backend/app/routers/` — HTTP endpoints

This directory defines every HTTP endpoint as a FastAPI `APIRouter`. [`../main.py`](../main.py) mounts all four routers under the `/api` prefix. Every path below is therefore served at `/api/...`, both directly on the backend (`:8000`) and through nginx (`:8080/api/...`).

A router's job is deliberately thin:
1. Declare the path, the request schema and the `response_model`.
2. Resolve **who is calling and what they may do** through `Depends(...)` guards from [`../common/dependencies.py`](../common/README.md).
3. Call a service function ([`../services/`](../services/README.md)).
4. `await db.commit()` after a write. Some writes rely on `get_db`'s commit-on-exit instead.
5. Return the result, which the `response_model` filters and validates.

[`__init__.py`](__init__.py) is empty.

## Files

| File | Prefix | Guard | Covers |
|---|---|---|---|
| [`health.py`](health.py) | — | none | Liveness probe |
| [`auth.py`](auth.py) | `/auth` | none / token-based | Login, SSO callback, temp-token exchange, refresh, logout |
| [`admin.py`](admin.py) | `/admin` | `require_admin` on **every** endpoint | Courses, rosters, staff, local users, course-access grants |
| [`qa.py`](qa.py) | — | `get_current_user`, `require_course_member`, `require_course_staff` | The course picker and the whole Q&A board |

`admin.py` runs most of its queries inline with `select(...)`, and calls services only for password hashing and the roster/staff CSV imports. `qa.py` hands all board logic to `qa_service`.

## Endpoints

### `health.py`

| Method & path | Returns |
|---|---|
| `GET /api/health` | `{"status": "ok"}`. It doesn't touch MySQL or Redis, so "ok" only means the process is up |

### `auth.py`

| Method & path | Rate limit | Behavior |
|---|---|---|
| `POST /api/auth/login` | 5 / 15 min | **`{username, password}`**: verifies a local account. Returns `{access_token}` and sets the `refresh_token` cookie. **`{netid}`**: development only (otherwise 401). Gets or creates the user, runs the roster sync, and returns `{temp_token}`, which the frontend then exchanges |
| `GET /api/auth/oauth2-callback?redirect_to=` | — | For the campus SSO proxy (details below) |
| `POST /api/auth/exchange-temp` | 10 / min | Bearer **temp** token → `{access_token}` + `refresh_token` cookie |
| `POST /api/auth/refresh` | — | `refresh_token` cookie → new `{access_token}`, and **rotates** the refresh cookie |
| `POST /api/auth/logout` | — | Clears the refresh cookie (204). There is no server-side revocation: issued tokens stay valid until they expire |

How the SSO callback works:
- It trusts the `X-Auth-Request-User` / `X-Auth-Request-Email` headers only if the request also carries `X-Proxy-Shared-Secret` equal to `OAUTH2_PROXY_SHARED_SECRET`, compared in constant time.
- If the secret is unset, the callback **fails closed**.
- It returns a small HTML page that redirects to `FRONTEND_URL + redirect_to`, with the temp token in the URL **fragment** (`#oauth2_data=...`), so it never reaches server logs.
- `redirect_to` is limited to `/student/login`, `/staff/login` and `/admin/login`.

The refresh cookie is `httpOnly`, `SameSite=Lax`, `Secure` outside development, and scoped to `path=/api/auth`. The browser only sends it to the auth endpoints.

### `admin.py` (all require a global `ADMIN`)

| Method & path | Behavior |
|---|---|
| `GET`, `POST /api/admin/courses` | List / create courses. **There is no delete-course endpoint** |
| `GET`, `PUT /api/admin/courses/{course_id}` | Read / rename a course or change its semester |
| `GET /api/admin/courses/{course_id}/roster` | Roster entries, sorted by name |
| `POST /api/admin/courses/{course_id}/roster` | Multipart Canvas CSV upload (capped at 2 MB), handled by `roster_service.process_roster_csv` |
| `POST /api/admin/courses/{course_id}/roster/import` | JSON rows `{rows: [{netid, full_name, email}]}` from the admin app's column-mapping wizard |
| `PATCH /api/admin/courses/{course_id}/roster/{roster_id}` | Edit one entry, or (de)activate it |
| `GET /api/admin/courses/{course_id}/staff` | Users with a `STAFF` grant in the course |
| `POST /api/admin/courses/{course_id}/staff` | Multipart staff CSV, handled by `staff_service.process_staff_csv`. Takes effect immediately |
| `GET`, `POST /api/admin/users` | List / create local username+password accounts (always `role="USER"` at creation) |
| `GET`, `PUT`, `DELETE /api/admin/users/{user_id}` | The `GET` includes `course_access`. The `PUT` can change the role to `ADMIN`. Deleting an `ADMIN` → 409 |
| `POST /api/admin/users/{user_id}/course-access` | `{course_id, role}`: grants access, or **changes the role** if a grant already exists |
| `DELETE /api/admin/users/{user_id}/course-access/{course_id}` | Revoke a grant |

### `qa.py` (the board)

| Method & path | Guard | Behavior |
|---|---|---|
| `GET /api/courses/mine` | logged in | The course picker: `[{id, name, semester, role}]`. An `ADMIN` gets **every** course with `role="STAFF"` |
| `GET /api/courses/{course_id}/categories` | member | List categories |
| `POST /api/courses/{course_id}/categories` | staff | Create a category (201, or 409 for a duplicate name) |
| `PATCH`, `DELETE /api/courses/{course_id}/categories/{category_id}` | staff | Edit / delete a category (the delete returns 204) |
| `GET /api/courses/{course_id}/questions?category_id=&status=&q=` | member | `QuestionSummary[]`, newest first. `status` must be `OPEN` or `CLOSED`, `q` ≤ 200 characters |
| `POST /api/courses/{course_id}/questions` | member | `{title, body, category_ids}` → 201 `QuestionDetail`. Students and staff can both ask |
| `GET /api/courses/{course_id}/questions/{question_id}` | member | `QuestionDetail` with every post |
| `POST /api/courses/{course_id}/questions/{question_id}/posts` | member | `{kind, body}` → 201 `QuestionDetail`. `author_role` is set from `member.course_role`. Posting to a closed thread → 409 |
| `PATCH /api/courses/{course_id}/questions/{question_id}/posts/{post_id}/accept` | staff | `{is_accepted}` → `QuestionDetail`. Only `ANSWER`s; accepting one un-accepts the others |
| `POST /api/courses/{course_id}/questions/{question_id}/close` | staff | → `QuestionDetail` (409 if already closed) |
| `POST /api/courses/{course_id}/questions/{question_id}/reopen` | staff | → `QuestionDetail` (409 if already open) |

"Member" means `require_course_member`; "staff" means `require_course_staff`. Both are explained in [`../common/README.md`](../common/README.md):
- A non-member gets **404**, not 403.
- A student calling a staff endpoint gets **403**.
- Anyone using the student app is treated as a student.

## Patterns to keep when adding endpoints

- **Every write in a thread returns the whole updated `QuestionDetail`**, not just the changed post, so a client can re-render the thread straight from the response.
- **Status codes:** 201 for creates, 204 for deletes, and 404/403/409/422 from the shared error handlers. Don't build `HTTPException`s by hand; raise the `QnaError` subclasses.
- **A rate-limited endpoint needs a `request: Request` parameter**, because slowapi reads it.
- **Guards come from the path.** `require_course_member` / `require_course_staff` read `course_id` from the URL, so a course-scoped endpoint must keep `{course_id}` in its path.

## Where the RAG feature will touch this directory

Notes for the design work (T3):

- **New router(s).** Resource registration, upload fallback, re-sync and `POST /api/courses/{course_id}/rag/compare` belong in a new module (e.g. `rag.py`), included in `main.py` with `prefix="/api"` like the others. All of them are staff-only, through `require_course_staff`.
- **`/rag/compare` is a dry run.** It must never call `qa_service.create_question` / `create_post` or commit anything. That is what makes it safe for the harness to call it once per question per configuration.
- **Each `/rag/compare` call must finish within 180 seconds.** `eval/compare_harness.py` uses `timeout=180` per call. nginx allows 300 s (`proxy_read_timeout` in `nginx/nginx.*.conf`), so the harness's 180 s is the real limit. The larger embedding model and generation models on a CPU-only VM need to fit inside it.
- **`create_question` in `qa.py` is the natural trigger point for AI answering.** The question has to be committed before an AI answer can be attached to it. How that runs relative to the student's request is the design question flagged in [`../services/README.md`](../services/README.md).
- **Upload size.** nginx accepts request bodies up to 50 MB (`client_max_body_size`). The backend's own cap comes from `read_upload_capped`'s `max_bytes`, which is 2 MB by default and needs raising for PDFs and zipped repositories.
