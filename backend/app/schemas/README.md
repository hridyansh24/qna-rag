# `backend/app/schemas/` — Pydantic request/response schemas

This directory defines the shape of every JSON body the API accepts or returns, as Pydantic v2 models. Routers use them in two ways:
- as typed parameters, for **request validation**
- as `response_model=`, for **response filtering and serialization**

Services import them too. For example, `qa_service.create_category` takes a `CategoryCreate`, and `roster_service` returns a `RosterUploadResult`. So these models are the contract between the HTTP layer and the business logic, not just between client and server.

[`__init__.py`](__init__.py) is empty. Import from the module directly, e.g. `from ..schemas.qa import PostCreate`.

## Files

| File | Used by | What it covers |
|---|---|---|
| [`auth.py`](auth.py) | [`routers/auth.py`](../routers/auth.py) | `LoginRequest` (username+password, **or** a dev-only `netid`), and the three token responses: `TokenResponse`, `TempTokenResponse`, `RefreshResponse` |
| [`admin.py`](admin.py) | [`routers/admin.py`](../routers/admin.py), roster/staff services | Courses, roster entries and CSV/row imports, staff CSV results, local user accounts, course-access grants |
| [`qa.py`](qa.py) | [`routers/qa.py`](../routers/qa.py), [`services/qa_service.py`](../services/qa_service.py) | Categories, questions (summary and detail), posts, accept toggles, and the course picker (`MyCourseResponse`) |

## Conventions

| Suffix | Role | Notes |
|---|---|---|
| `…Create` | Request body for creating something | Required fields with length limits |
| `…Update` / `…Patch` | Partial update | Every field optional (`None` = "leave unchanged"). The router/service applies only the non-`None` fields |
| `…Response` / `…Summary` / `…Detail` | Response body | Output only |
| `…Result` | Outcome of a bulk operation | e.g. `RosterUploadResult` reports `imported` / `updated` / `deactivated` / `errors` counts instead of failing the whole upload on one bad row |

- **Every request model sets `model_config = ConfigDict(extra="forbid")`.** An unknown field in a request body is rejected with a 422, not silently ignored. The error body is `{"error": "VALIDATION_ERROR", "detail": [...]}`, produced by the handler in [`common/exceptions.py`](../common/exceptions.py).
- **Response models are filled in two different ways.**
  - `CategoryResponse`, `CourseResponse`, `RosterEntryResponse` and `UserResponse` set `from_attributes=True`, so a router can return the ORM object directly.
  - `QuestionSummary`, `QuestionDetail` and `PostResponse` don't. They are always built from the plain dicts produced by `qa_service.serialize_*`, which flatten nested users into `AuthorSummary` (`{id, display_name}`). The only nested ORM objects in those dicts are the `Category` rows under `categories`, which `CategoryResponse` reads with `from_attributes`.
- **Enumerated values are validated with regex patterns, not Python `Enum`s.** Examples: `PostCreate.kind` (`^(ANSWER|FOLLOWUP)$`), `CourseAccessGrant.role` (`^(STUDENT|STAFF)$`), `UserUpdate.role` (`^(USER|ADMIN)$`). Response fields such as `status`, `kind` and `author_role` are typed as plain `str`, so a new database enum value passes through responses with no schema change.

## Validation rules worth knowing

- `QuestionCreate.category_ids` has `min_length=1`. **Every question must carry at least one category.** The service then checks that each id belongs to the course.
- `QuestionCreate.body` and `PostCreate.body` are capped at 10,000 characters. Titles at 255.
- `UserCreate`/`UserUpdate`:
  - `username` is lowercased by a `field_validator` and limited to `[a-zA-Z0-9_-]`, 3–50 characters
  - `password` is 8–**72** characters; 72 is bcrypt's input limit
- `LoginRequest.check_credentials` is a `model_validator` that raises a plain `ValueError` if neither credential form is present. That is why `common/exceptions.py` runs validation errors through `jsonable_encoder`: without it, the raw exception object in the error context would crash JSON serialization and turn a 422 into a 500.
- **Length limits don't always match the database.**
  - `RosterRowIn.netid` and `RosterEntryPatch.netid` allow up to 100 characters, but `course_rosters.netid` is `String(50)`.
  - `RosterRowIn.email` is a plain `str`, while `RosterEntryPatch.email` is validated as `EmailStr`.
- `UserWithAccessResponse.course_access` is an untyped `list[dict]`. Each entry is `{course_id, role}`, built by hand in `routers/admin.py:get_user`.

## Where the RAG feature will touch this directory

Notes for the design work (T3):

- **`PostResponse` needs new fields.** It is the shape both the student and staff apps render for every thread entry. Labeling a post as AI-generated and carrying its citation(s) means adding fields here, and the services' `serialize_post` must fill them.
- **`POST /api/courses/{course_id}/rag/compare` has a fixed contract**, given in `instructions.md` (T6). Its request and response schemas, likely in a new `schemas/rag.py`, must match that contract field for field. `eval/compare_harness.py` sends exactly the five documented request fields (`question`, `ingestion_profile`, `similarity_threshold`, `system_prompt`, `generation_model`), so `extra="forbid"` is safe there.
- **Resource registration and re-sync** need their own create/response schemas: URL, resource type, ingestion profile and chunking configuration. Upload-fallback endpoints take multipart files, like `routers/admin.py:upload_roster`, not JSON bodies.
