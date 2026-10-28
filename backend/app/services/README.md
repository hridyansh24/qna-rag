# `backend/app/services/` — Business logic

This directory holds the logic between the HTTP layer ([`../routers/`](../routers/README.md)) and the database ([`../models/`](../models/README.md)):
- the Q&A board's rules
- token and password handling
- roster and staff imports
- startup bootstrapping

Every function is `async` and takes an `AsyncSession` as its first argument.

[`__init__.py`](__init__.py) is empty. Routers import modules (`from ..services import qa_service`) or individual functions.

## Transaction convention

**Services `flush()`; they never `commit()`.** Flushing sends the SQL and assigns generated ids, but the transaction stays open. The caller decides when it's done:
- Most routers call `await db.commit()` explicitly after a write.
- The rest rely on `database.get_db`, which commits once the request finishes without error and rolls back if an exception escapes.

The one exception is [`bootstrap.py`](bootstrap.py). It runs outside any request, so it opens its own `AsyncSessionLocal()` sessions and commits them itself.

## Files

| File | Called from | Responsibility |
|---|---|---|
| [`qa_service.py`](qa_service.py) | `routers/qa.py` | Categories, questions, posts, accept/unaccept, close/reopen, plus the `serialize_*` helpers that build API response dicts |
| [`auth_service.py`](auth_service.py) | `routers/auth.py`, `common/dependencies.py`, `routers/admin.py`, `bootstrap.py` | bcrypt passwords, RS256 JWT creation/verification, user lookup, netid get-or-create, roster → access sync at login |
| [`roster_service.py`](roster_service.py) | `routers/admin.py` | Canvas gradebook CSV (or pre-mapped rows) → `course_rosters` upsert + deactivation |
| [`staff_service.py`](staff_service.py) | `routers/admin.py` | Staff CSV → create accounts and grant `STAFF` access immediately |
| [`bootstrap.py`](bootstrap.py) | `main.py` lifespan | First admin account and the AI system user at startup |

## `qa_service.py` — the thread model

### Loading a question

`_question_load_options()` eager-loads everything a response needs: the author, `closed_by`, categories (through `QuestionCategory`), every post, and each post's author and `accepted_by`. All of it is loaded with `selectinload`. **This matters under async SQLAlchemy:** touching a relationship that wasn't loaded raises an error instead of quietly lazy-loading it. Any new relationship that a serializer reads has to be added here.

`_get_question(db, course_id, question_id)` is the single way a question is fetched.
- It always filters by **both** `question_id` and `course_id`, so a question can't be reached through another course's URL (it returns 404 instead).
- It uses `populate_existing=True`. Each write function loads the question, changes it, flushes, then calls `_get_question` **again** and returns that fresh copy. Without the option, the second load would return the cached object with a stale `posts` list.

Every write function in this file returns the reloaded **whole `Question`**, not the single row it changed. The routers turn it into a `QuestionDetail`.

### Rules enforced here (not in the database)

| Function | Rule |
|---|---|
| `create_question` | Every `category_ids` entry must belong to this course → otherwise `404` listing the unknown ids. At least one category is required by the schema |
| `create_post` | Posting to a `CLOSED` question → `409`. Any member may post either `kind`; students can post `ANSWER`s. `author_role` is **passed in by the caller**, not looked up here |
| `set_post_accepted` | Only `kind == "ANSWER"` → otherwise `409`. Accepting one post un-accepts every other post in the question (**at most one accepted answer**). Un-accepting clears `accepted_by`/`accepted_at`. It does **not** check the question's status, so answers on a closed thread can still be accepted or un-accepted |
| `close_question` / `reopen_question` | Closing a closed thread (or reopening an open one) → `409`. They set or clear `closed_at` and `closed_by_user_id` |
| `create_category` | A duplicate name in the course → `409`. `update_category` does **not** pre-check this, so renaming onto an existing name relies on the database's unique constraint |

Accepting and closing are independent. Accepting an answer doesn't close the thread, and closing doesn't need an accepted answer.

### Listing and search

`list_questions` returns a course's questions newest first, with optional filters for `category_id` (join through `QuestionCategory`), `status`, and `q`.
- `q` is a plain `LIKE '%q%'` over title **or** body. There's no full-text index or ranking.
- There's no pagination, and every question's posts are eager-loaded so the serializer can compute `post_count` and `has_accepted_answer`.

### Serializers

`serialize_post`, `serialize_question_summary` and `serialize_question_detail` turn ORM objects into the dicts behind `PostResponse`, `QuestionSummary` and `QuestionDetail`.
- People are always flattened to `author_summary(user) = {id, display_name}`.
- `display_name()` falls back through `display_name → username → netid → "Unknown"`. That fallback matters because users created through SSO or the dev netid login get **no** `display_name`.
- `post_count` counts follow-ups as well as answers.

## `auth_service.py` — identity and tokens

**Passwords** are hashed with passlib's bcrypt context, 12 rounds.

**Keys.**
- `JWT_PRIVATE_KEY` / `JWT_PUBLIC_KEY` are **base64-encoded PEM** strings.
- If either is unset, or fails to decode, the service generates one ephemeral RSA key pair per process and logs `jwt_keys_not_configured`. Every restart then invalidates all issued tokens.

**Tokens.** All are RS256 with `sub` = user id and a `token_type` claim.

| Token | Lifetime | Issued by | Notes |
|---|---|---|---|
| `access` | 2 hours | login, exchange-temp, refresh | Also carries `role` |
| `refresh` | 7 days | same | Sent as an httpOnly cookie scoped to `/api/auth` |
| `temp` | 15 minutes | SSO callback, dev netid login | Exchanged for access+refresh at `/api/auth/exchange-temp` |

**`get_or_create_user_by_netid(db, netid, email)`** is the single path for SSO and dev logins.
- It finds or creates a `role="USER"` account and updates `last_login`.
- It then calls `_sync_roster_course_access`: for every **active** roster row matching the netid, if the user has no access row for that course yet, it adds `UserCourseAccess(role="STUDENT")`.
- That sync **only ever adds** access. Deactivating a roster entry never revokes an existing grant, and it never downgrades an existing `STAFF` grant.

**`authenticate_local`** checks username (lowercased) and password for local accounts. It returns `None` on any failure and logs `login_failed`.

## `roster_service.py` — student roster (bookkeeping only)

`process_roster_csv` reads a Canvas gradebook export.
- Text decoding: UTF-8 with BOM, falling back to Latin-1.
- Required columns, matched case-insensitively: `Student` (`"Last, First [Middle]"`) and `SIS Login ID` (`"NETID@WISC.EDU"`).
- It skips Canvas's "Points Possible" row and blank rows.
- The stored name is the given name(s) only, title-cased (`"Bachu, Revanth Krishna"` → `"Revanth Krishna"`). The netid and email are lowercased.

`process_roster_rows` does the same from rows the admin app's column-mapping wizard has already mapped.

Both functions:
- **upsert** by `(course_id, netid)`
- **deactivate** every active entry missing from the upload (an upload is the full current roster)
- stop at `MAX_ROWS = 1000`
- collect per-row problems in `errors` instead of failing the whole upload

Neither creates `User`s nor grants access. That happens later, at login.

## `staff_service.py` — staff list (takes effect immediately)

`process_staff_csv` reads `netid, full_name, email` (case-insensitive headers, `MAX_ROWS = 200`, a duplicate netid in the same file is an error). For each row:
1. **Account:** create the `User` if no account has that netid (`role="USER"`, no password; they sign in through SSO). An existing user gets a missing email or display name filled in.
2. **Access:** grant `STAFF` access, or upgrade an existing `STUDENT` grant. Rows that are already `STAFF` are counted in `already_staff`.

## `bootstrap.py` — startup accounts

`bootstrap_admin()` runs in `main.py`'s lifespan, before the app serves traffic. It does two things:
1. **First admin.** If `ADMIN_USERNAME`/`ADMIN_PASSWORD` are set and no admin exists, it creates one. After that, the env vars are ignored.
2. **AI system user.** On **every** startup, it makes sure the `qna-assistant` user that authors AI answers exists, with no password, no netid and role `USER`, so nobody can sign in as it.

On a fresh database it retries every 5 seconds, logging `admin_bootstrap_waiting_for_schema` until `alembic upgrade head` creates the tables. **Startup blocks until then.** That's why a fresh deployment needs migrations run before (or as part of) starting the backend.

## Where the RAG feature will touch this directory

Notes for the design work (T3). These describe constraints, not decisions:

- **The hook point is right after a question is created.** `create_question` → (commit) → retrieve → maybe post an AI answer. CPU-only generation takes seconds to minutes, so doing it inside the student's `POST /questions` request would hold that request open the whole time. Generating outside the request (a background task or a worker) means the generator can't reuse the request's session: it needs its own `AsyncSessionLocal()` session and its own commit, the same pattern `bootstrap.py` uses.
- **`create_post` can create the AI post if it accepts the new author role.** It already rejects closed threads and needs an author `User` plus an `author_role`. Accepting the AI answer then needs nothing new: `set_post_accepted` works on any `ANSWER`.
- **`serialize_post` (and possibly `_question_load_options`) must carry the AI label and citations** for the frontends to render them.
- **Historical Q&A ingestion can reuse `_question_load_options`.** It reads closed and/or accepted threads with their posts.
- **New services (ingestion, retrieval/generation, clients for Ollama, Infinity and ChromaDB) should stay non-blocking.** Use async HTTP clients, or run synchronous libraries and CPU-heavy work (HTML stripping, PDF text extraction, chunking) in a thread pool, so one ingestion doesn't block every other request on the event loop.
