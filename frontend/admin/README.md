# frontend/admin — Administration app

The React SPA global admins use to set up the system: create courses, upload student rosters and staff lists, create local accounts, and grant or revoke per-course access by hand. It doesn't touch questions or posts at all. It is served at `/admin/` in production.

Every call goes to `/api/admin/*`, which the backend protects with `require_admin` (the user's `role` must be `ADMIN`). Unlike the other two apps, this one sends **no** `X-App-Surface` header, and it has no course context.

## Stack

The same as the other apps: Vite 5, React 18, TypeScript, react-router-dom 6, Tailwind 3 and lucide-react. `components/ui/*`, `utils.ts`, `index.css` and `tailwind.config.ts` are identical to the student and staff copies.

## Layout

```
admin/
├── index.html
├── vite.config.ts        # base '/admin/' in prod; dev port 5175; proxies /api → localhost:8000
└── src/
    ├── main.tsx
    ├── App.tsx           # router, RequireAdmin guard, sidebar layout (Courses / Users / Logout)
    ├── index.css
    ├── lib/
    │   ├── api.ts        # same fetch wrapper as other apps, minus X-App-Surface, plus postForm()
    │   └── utils.ts      # cn()
    ├── components/ui/    # Button, Badge, Card, Input, Textarea
    └── pages/
        ├── LoginPage.tsx
        ├── CoursesPage.tsx
        ├── RosterPage.tsx
        ├── UsersPage.tsx
        └── UserDetailPage.tsx
```

There is no `types.ts` and no `CourseContext`. Each page declares the response interfaces it uses inline, at the top of the file.

## Routes (`App.tsx`)

| Path | Page | Backend calls |
|---|---|---|
| `/login` | `LoginPage` | `POST /auth/login` (username/password only, no dev netid login) |
| `/courses` | `CoursesPage` | `GET/POST /admin/courses`, `PUT /admin/courses/{id}` |
| `/courses/:courseId/roster` | `RosterPage` | `GET/POST /admin/courses/{id}/roster`, `PATCH …/roster/{rosterId}`, `GET/POST /admin/courses/{id}/staff` |
| `/users` | `UsersPage` | `GET/POST /admin/users` |
| `/users/:userId` | `UserDetailPage` | `GET /admin/users/{id}`, `GET /admin/courses`, `POST /admin/users/{id}/course-access`, `DELETE …/course-access/{courseId}` |
| `*` | redirect to `/courses` | |

`RequireAdmin` only checks that a token exists. It doesn't check the role. A non-admin who logs in here gets in, but every page then fails with 403 (Forbidden), and the error shows inline or the page stays empty.

## Data flow by page

- **CoursesPage**: lists the courses, with inline forms to create one (name and semester) or edit one. Each course row links to its Roster page.
- **RosterPage** has two independent sections, and each uploads a CSV with `api.postForm()` (multipart, with no JSON `Content-Type`):
  - **Student roster** (a Canvas gradebook export with `Student` and `SIS Login ID` columns). This creates `CourseRoster` rows, and re-uploading deactivates any netid missing from the new file. It does **not** grant access right away: the backend grants `STUDENT` access the next time that netid logs in through SSO or dev login (`auth_service._sync_roster_course_access`). The page shows the counts (imported, updated, deactivated) and any row errors. Each row's Active/Inactive button sends `PATCH {is_active}`.
  - **Staff CSV** (`netid`, `full_name` and `email` columns). This takes effect immediately: it creates any missing accounts and grants `STAFF` access. The page shows the counts (created, granted, already staff) and the current staff list.
  - The backend caps uploads at 2 MB.
- **UsersPage**: lists every user. It can create a *local* (username/password) account for someone without campus SSO. Clicking a row opens its detail page.
- **UserDetailPage**: shows one user's global role and their per-course `STUDENT`/`STAFF` grants, with a form to grant access (course plus role) and a button to revoke each grant. This is the manual path to `UserCourseAccess`; the other two paths are roster sync at login and the staff CSV.

## Things to know before changing it

- **Missing UI.** There is no UI for deleting a user (`DELETE /admin/users/{id}`), editing one (`PUT /admin/users/{id}`), or bulk-importing roster rows (`POST …/roster/import`), although the backend has endpoints for all three.
- **Failures can be silent.** Several actions don't catch errors: toggling a roster entry, revoking access, and loading the user lists. When one of those fails, nothing appears on screen.
- **The token is shared in production.** As in the other apps, the token lives in `localStorage.token`, and in production all three apps share that one origin. Logging out of admin also logs you out of student and staff.

## Running

```bash
npm install
npm run dev          # http://localhost:5175, API proxied to :8000
npm run build        # → dist/ (mounted by nginx at /admin/)
npx tsc --noEmit
```
