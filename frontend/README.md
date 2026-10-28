# frontend — The three React apps

QnA's UI is three independent single-page apps. Each has its own `package.json`, `node_modules`, build and dev port, and no code is shared between them. Each app's README goes deeper:

| App | Who uses it | Prod path | Dev port | README |
|---|---|---|---|---|
| `student/` | Students: browse, ask, answer, follow up | `/student/` (`/` redirects here) | 5173 | [student/README.md](student/README.md) |
| `staff/` | Course staff: everything above, plus categories, verify answers, close/reopen threads | `/staff/` | 5174 | [staff/README.md](staff/README.md) |
| `admin/` | Global admins: courses, rosters, staff lists, users, course access | `/admin/` | 5175 | [admin/README.md](admin/README.md) |

## How they fit together

```
            ┌────────── nginx :8080 (prod/compose) ──────────┐
 browser ──►│ /student/  /staff/  /admin/  → each app's dist/│
            │ /api/*                        → backend :8000  │
            └────────────────────────────────────────────────┘
 dev:  vite :5173 / :5174 / :5175  ── proxy /api ──► backend :8000
```

- **Talking to the API.** All three use the same small `lib/api.ts` wrapper around `fetch`:
  - It sends a `Bearer` JWT from `localStorage.token`.
  - It turns a non-2xx response into `Error(body.message)`, and pages show that message inline.
  - Each app's `vite.config.ts` sets `base` to its subpath in production builds, so nginx can serve them side by side.
- **Who is permitted to do what.** The backend decides, never the UI:
  - The student and staff apps send an `X-App-Surface` header (`student` or `staff`). `student` forces the caller's course role down to `STUDENT`, even for staff and admins. `staff` changes nothing, because the caller's real `UserCourseAccess` role still decides. See `backend/app/common/dependencies.py`.
  - The admin app sends no surface header, and its endpoints require a global `ADMIN`.
- **Course scope.** The student and staff apps share a `CourseContext`. It loads `GET /courses/mine`, keeps the selected course in `localStorage.course_id`, and every page builds `/courses/{courseId}/…` URLs from it. The admin app works across all courses and has no course context.
- **Duplication.** `staff/` is a near-copy of `student/`. Roughly 15 files are byte-identical, including `types.ts`, `CourseContext.tsx`, `components/ui/*`, `QuestionsPage.tsx` and the configs. `admin/` shares only the UI primitives and configs. A cross-cutting change, such as T8 theming or a new `author_role` for AI answers, has to be made in each app that needs it.

## Common commands (from the repo root)

```bash
npm run install:all     # npm install in all three apps
npm run dev             # all three dev servers via concurrently
npm run dev:student     # or :staff / :admin
npm run build           # build all three into their dist/ (nginx mounts these)
```

CI (`.gitlab-ci.yml`, `frontend-typecheck`) runs `npx tsc --noEmit` in each app on every merge request, and any type error fails the pipeline.

## Cross-app gotchas

- **Expired tokens aren't handled.** Auth guards only check that a token is present, and nothing calls `/auth/refresh`. When the 2-hour access token expires, requests fail until the user logs in again.
- **Shared storage in production.** All three apps share one origin there, so they share `localStorage`. Logging in or out in one app affects the other two. In dev they run on separate ports, so each has its own storage.
- **Colors are hard-coded.** Styling uses raw Tailwind palette classes in a single dark look, with no semantic tokens. T8 replaces this with a light/dark token system.
- **Post bodies render as plain text** (`whitespace-pre-wrap`). Showing AI citations as links needs a rendering change in both the student and staff `QuestionDetailPage`.
