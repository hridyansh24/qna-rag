# frontend/staff — Course staff app

The React SPA course staff (TAs and instructors) use to run a course board. It has everything the student app has, plus managing categories, marking answers verified (accepted), and closing or reopening threads. It is served at `/staff/` in production.

This app sends `X-App-Surface: staff`. That header grants nothing by itself: the backend works out the caller's real course role first. A user with only `STUDENT` access who logs in here can still use the shared pages, but every staff-only button returns 403 (Forbidden). Global admins count as `STAFF` in every course.

## Relationship to `frontend/student/`

This app started as a copy of the student app and still mostly is one. The following files are **identical** in both: `CourseContext.tsx`, `utils.ts`, `theme.ts`, `useAiAnswerPolling.ts`, `components/Citations.tsx`, `components/RoleBadge.tsx`, `components/ThemeToggle.tsx`, `pages/SourceViewerPage.tsx`, `components/ui/*`, `QuestionsPage.tsx`, `main.tsx`, `index.css`, `tailwind.config.ts`, `postcss.config.js` and the `tsconfig` files. Read [../student/README.md](../student/README.md) for the shared stack, the login and course-selection flow, `api.ts`, and the cross-app gotchas (expired tokens, theme tokens, plain-text post bodies, the token shared in production). This README covers only what's different.

| File | Difference from student |
|---|---|
| `vite.config.ts` | `base: '/staff/'` in prod; dev port **5174** |
| `index.html` | Title `QnA — Staff` |
| `src/lib/api.ts` | `APP_SURFACE = 'staff'`; adds `postForm()` and `putForm()` for uploads |
| `src/lib/types.ts` | Appends the resource, profile, run and settings shapes (§9.6) |
| `src/App.tsx` | Header reads "Course Q&A — Staff" (not the course name) and has `NavLink`s to Questions, **Categories** and **Resources**. Adds those two routes |
| `src/pages/LoginPage.tsx` | Heading only ("Staff Login") |
| `src/pages/AskQuestionPage.tsx` | The empty-categories hint points at the Categories page |
| `src/pages/QuestionDetailPage.tsx` | Staff controls (see below); the composer defaults to `ANSWER` |
| `src/pages/CategoriesPage.tsx` | **Staff-only page** |
| `src/pages/ResourcesPage.tsx`, `src/components/resources/*` | **Staff-only page** (see below) |

## Routes

| Path | Page |
|---|---|
| `/login` | `LoginPage` |
| `/questions` | `QuestionsPage` (identical to student) |
| `/questions/new` | `AskQuestionPage` |
| `/questions/:questionId` | `QuestionDetailPage` (with staff controls) |
| `/sources/:resourceId/*` | `SourceViewerPage` (identical to student) |
| `/categories` | `CategoriesPage` |
| `/resources` | `ResourcesPage` |
| `*` | redirect to `/questions` |

## Staff-only data flow

**`QuestionDetailPage.tsx`** adds two actions. Both share one `busy` flag, and the response from each replaces the local `question` state with the updated `QuestionDetail`:

- **Close/Reopen thread** (button next to the status badge): `POST /courses/{id}/questions/{qid}/close` or `…/reopen`, depending on the current status. Closing hides the composer. Reopening brings it back.
- **Mark verified / Verified** (on every `ANSWER` post, not on follow-ups): `PATCH …/posts/{pid}/accept {is_accepted: bool}`. The backend allows only one accepted answer per question, so accepting one answer un-accepts any other. "Verified" in the UI means the same as `is_accepted` in the API. It is disabled on a hidden post, which the backend would reject with 409.
- **Hide from students / Unhide** (on AI posts only): `PATCH …/posts/{pid}/hide {is_hidden: bool}`. Hiding an accepted AI answer also un-accepts it, server-side (`docs/design-rag.md` §6.5). Hidden posts show as a dashed card with a "Hidden from students" badge.
- **AI status line** under the question, for every final `ai_status` except `ANSWERED` (e.g. "AI: no source cleared the threshold"), so staff can see why a question has no AI answer. Students see nothing for these.

Staff can still post into an `OPEN` thread with the same composer students use. The backend records their `author_role` as `STAFF`, so the post gets the "Course Staff" badge.

**`CategoriesPage.tsx`**:
- Lists categories with `GET /courses/{id}/categories`.
- Creates one with `POST … {name, description}`. A duplicate name returns 409 (Conflict) and the message is shown inline.
- Deletes one with `DELETE …/{categoryId}`. There's no confirmation step, and errors are not caught, so a failed delete fails silently.

The backend also has `PATCH /courses/{id}/categories/{cid}` for renaming a category, but no UI calls it yet.

**`ResourcesPage.tsx`** (T4, `docs/design-rag.md` §10, step 8) manages the course's RAG sources, through the §9.5 endpoints:
- **Sources:** each resource with its latest run in every profile, and Sync per profile. The list polls every 3 s while any run is `QUEUED` or `RUNNING`. Upload resources can be replaced (`putForm`); any resource but QA_HISTORY can be deleted. Both wait for active runs, which the backend would reject with 409.
- **Add a source:** by URL (the primary path) or by upload, with the Source path the eval harness matches on (§5.5).
- **Ingestion profiles:** create from a preset or a custom chunking config, and Sync all. Profiles are immutable.
- **Auto-responder settings:** `GET`/`PUT …/rag/settings`. The backend checks the active profile and the model, and its 422 messages show on the form.

Use a scratch course to try it, not the eval course (course 1): syncs, uploads and deletes there change the graded corpus (§11.2).

## Running

```bash
npm install
npm run dev          # http://localhost:5174, API proxied to :8000
npm run build        # → dist/ (mounted by nginx at /staff/)
npx tsc --noEmit
```
