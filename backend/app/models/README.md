# `backend/app/models/` — SQLAlchemy ORM models

This directory defines every database table the backend uses, as SQLAlchemy 2.0 typed models (`Mapped[...]` / `mapped_column`). All of them inherit from `Base` in [`../database.py`](../database.py). [`__init__.py`](__init__.py) re-exports every model, and that import is what registers the tables on `Base.metadata`. Alembic's [`../migrations/env.py`](../migrations/env.py) imports `app.models` for exactly this reason, so `alembic revision --autogenerate` only sees models that `__init__.py` imports.

Models hold structure and relationships only. They contain no business rules: "at most one accepted answer", "closed threads take no posts" and every permission check live in [`../services/`](../services/README.md) and [`../common/dependencies.py`](../common/README.md).

## Files

| File | Tables | What it covers |
|---|---|---|
| [`user.py`](user.py) | `users` | Every account: SSO/netid users, local username+password accounts, the bootstrap admin |
| [`course.py`](course.py) | `courses`, `course_rosters`, `user_course_access` | The course scope, gradebook roster bookkeeping, and the per-course login grant |
| [`qa.py`](qa.py) | `categories`, `questions`, `question_categories`, `posts` | The Q&A board: tags, threads and every entry in a thread |

The schema in these files matches the single migration, [`../migrations/versions/001_initial_schema.py`](../migrations/versions/001_initial_schema.py).

## How the tables relate

```
User ──< UserCourseAccess >── Course ──< CourseRoster      (roster matched to User by netid string, no FK)
 │                              │
 │                              ├──< Category ──< QuestionCategory >── Question
 │                              │                                         │
 └── authors ──────────────────────────────────────────────────────────> Question ──< Post
     (also closed_by on Question, accepted_by on Post)                            (ordered by created_at)
```

- **`Course`** is the scope everything else lives in. Deleting a course cascades to its roster, access grants, categories and questions, both in the ORM (`cascade="all, delete-orphan"`) and in the database (`ondelete="CASCADE"`).
- **`CourseRoster`** is bookkeeping for a Canvas gradebook import: `netid`, `full_name`, `email`, `is_active`, unique per `(course_id, netid)`. It has **no foreign key to `users`**. A roster row grants nothing on its own. When a user logs in, `auth_service._sync_roster_course_access` looks up active roster rows by netid and creates `UserCourseAccess` rows for them.
- **`UserCourseAccess`** is the real permission grant. Its primary key is the composite `(user_id, course_id)`, so a user has exactly one role per course: `STUDENT` or `STAFF`.
- **`Category`** is a staff-managed tag, unique per `(course_id, name)`. **`QuestionCategory`** is the many-to-many join (composite primary key), so a question can carry several categories.
- **`Question`** is the root of a thread: `title`, `body`, `status` (`OPEN`/`CLOSED`), plus `closed_at`/`closed_by_user_id` set by staff. `Question.posts` is loaded ordered by `Post.created_at`. A composite index on `(course_id, status)` serves the board's list/filter query.
- **`Post`** is every entry in a thread:
  - `kind`: `ANSWER` (can be accepted) or `FOLLOWUP` (discussion, never accepted)
  - `author_role`: `STUDENT`/`STAFF`, a **snapshot** taken when the post was written, so a "Course Staff" badge doesn't change if the author's access changes later
  - `is_accepted`, `accepted_by_user_id`, `accepted_at`: set when staff accept the answer

  A composite index on `(question_id, created_at)` serves loading a thread in order.

## Two separate role systems

Easy to mix up:

| Column | Values | Scope | Meaning |
|---|---|---|---|
| `User.role` | `ADMIN`, `USER` | Global | `ADMIN` can use the admin API and is treated as `STAFF` in **every** course without needing a `UserCourseAccess` row (enforced in `common/dependencies.py`, not here) |
| `UserCourseAccess.role` | `STUDENT`, `STAFF` | One course | What a normal `USER` may do in that course |
| `Post.author_role` | `STUDENT`, `STAFF` | One post | A frozen copy of the author's *effective* role when they posted (see the `X-App-Surface` note in [`../common/README.md`](../common/README.md)) |

## Things that are not obvious from a quick read

- **Account identity is nullable on purpose.** `netid`, `email`, `username` and `password_hash` are all nullable and unique where present. SSO users have a `netid` and no password. Local accounts (the admin, users made in the admin app) have `username` and `password_hash` and usually no `netid`. `User.id` is a UUID string (`String(36)`), not an integer like every other table.
- **Some invariants are enforced in code, not the schema.** "At most one accepted post per question" and "only `ANSWER` posts can be accepted" are enforced in `qa_service.set_post_accepted`. Nothing in the database stops two accepted posts. `has_accepted_answer` in the API is computed from the posts, not stored.
- **Author foreign keys have no `ON DELETE` rule.** `questions.author_user_id`, `questions.closed_by_user_id`, `posts.author_user_id` and `posts.accepted_by_user_id` are plain foreign keys to `users.id`. MySQL's default is `RESTRICT`, so it refuses to delete a user who authored or closed anything. Every other foreign key cascades.
- **All enums are native MySQL `ENUM` columns** (`user_role`, `course_role`, `question_status`, `post_author_role`, `post_kind`). Adding a value means a migration that alters the column. Check that an autogenerated migration actually contains that change; don't assume it caught it.
- **Timestamps are timezone-naive `DATETIME`.** `created_at` defaults on the server (`func.now()`). `Question.updated_at` uses `onupdate=func.now()`, so it changes only when the question row itself is updated (e.g. close/reopen), **not** when someone posts in the thread.

## Where the RAG feature will touch this directory

Notes for the design work (T3). These are constraints the current schema puts on the design, not decisions:

- **AI answers need a new `Post.author_role` value.** The instructions require extending the schema, not reusing `STAFF`. Because the column is a native `ENUM`, that is an `ALTER` migration.
- **`Post.author_user_id` is `NOT NULL`.** An AI post needs an author: either a dedicated system user, or a nullable column. Either choice affects `serialize_post`, which calls `author_summary(post.author)` unconditionally.
- **Accepting AI answers works already.** The accept path works on any `ANSWER` post, so an AI post with `kind="ANSWER"` can be accepted with no new code path.
- **Citations have nowhere to live yet.** Registered resources, ingestion profiles and citation metadata will be new tables. Each new model file must be imported in `__init__.py` or Alembic won't see it.
- **Historical Q&A is already in these tables.** It's `Question`s with `status="CLOSED"` and/or an accepted `Post`. The ingester reads them here; it needs no new storage of its own.
