# frontend/student — Student app

The React SPA students use to browse a course's Q&A board, ask questions, and post answers or follow-ups. It is served at `/student/` in production; `/` redirects here.

This app sends `X-App-Surface: student` on every request. The backend then treats the caller as a `STUDENT` in every course, even if the account is really course staff or a global admin. A staff member testing this app sees and does exactly what a student would.

## Stack

Vite 5, React 18, TypeScript, react-router-dom 6, Tailwind 3, and lucide-react icons. There is no state library and no data-fetching library: each page calls `api` inside `useEffect` and keeps the result in local `useState`.

## Layout

```
student/
├── index.html            # Vite entry HTML (<title>QnA — Student</title>)
├── vite.config.ts        # base '/student/' in prod, '/' in dev; dev port 5173; proxies /api → localhost:8000
├── tailwind.config.ts    # system font stack only — no custom colors yet
└── src/
    ├── main.tsx          # mounts <App/> in StrictMode
    ├── App.tsx           # router, auth guard, header layout with course picker + logout
    ├── index.css         # Tailwind directives + hard-coded dark body background (#0f172a)
    ├── lib/
    │   ├── api.ts        # fetch wrapper: JWT + X-App-Surface headers, error → Error(message)
    │   ├── CourseContext.tsx  # which courses the user can see, and which one is selected
    │   ├── types.ts      # TS mirrors of backend response schemas (Question, Post, Category, …)
    │   └── utils.ts      # cn() = clsx + tailwind-merge
    ├── components/ui/    # Button, Badge, Card(+Header/Content), Input, Textarea (shadcn-style)
    └── pages/
        ├── LoginPage.tsx
        ├── QuestionsPage.tsx
        ├── AskQuestionPage.tsx
        └── QuestionDetailPage.tsx
```

## Routes (`App.tsx`)

| Path | Page | Notes |
|---|---|---|
| `/login` | `LoginPage` | Public |
| `/questions` | `QuestionsPage` | Behind `RequireAuth` and inside `Layout` |
| `/questions/new` | `AskQuestionPage` | |
| `/questions/:questionId` | `QuestionDetailPage` | |
| `*` | redirect to `/questions` | |

`RequireAuth` only checks that `localStorage.token` exists. It doesn't check whether the token is still valid. Access tokens last 2 hours and the app never calls `/auth/refresh`, so once a token expires, API calls fail and the error shows up inline on each page. The user is not sent back to `/login`; they have to log out and log in again.

## Data flow

1. **Login** (`LoginPage`) offers two forms:
   - **Username/password:** `POST /auth/login` returns `access_token`.
   - **Dev netid login:** `POST /auth/login {netid}` returns a `temp_token`, which is exchanged at `POST /auth/exchange-temp` for an `access_token`. The backend allows this only when `APP_ENV=development`. It stands in for campus SSO.

   Either way the token is stored in `localStorage.token`. The page then calls `CourseContext.refresh()` and goes to `/questions`.
2. **Course selection** (`CourseContext`): `GET /courses/mine` lists the courses the user can see. The selected `courseId` is kept in `localStorage.course_id` and falls back to the first course. The header shows a picker only when the user has more than one course. Every page reads `courseId` from `useCourse()` and builds `/courses/{courseId}/…` URLs from it.
3. **Board** (`QuestionsPage`):
   - `GET /courses/{id}/categories` fills the category filter.
   - `GET /courses/{id}/questions?q=&category_id=&status=` loads the list. It refetches on every change to the filters, including every keystroke in the search box (there's no debounce).
   - Each row shows the title, author, reply count, `OPEN`/`CLOSED` badge and category badges, plus a check icon when `has_accepted_answer` is true.
4. **Ask** (`AskQuestionPage`): loads the categories, requires at least one to be selected (the backend enforces `min_length=1` as well), then `POST /courses/{id}/questions` and navigates to the new thread.
5. **Thread** (`QuestionDetailPage`):
   - `GET /courses/{id}/questions/{qid}` returns the question and all of its posts in order.
   - Each post shows the author, a role badge (`Course Staff` or `Student`, from `author_role`), a kind badge (`Answer` or `Follow-up`), and "Verified by staff" when `is_accepted` is true.
   - If the thread is `OPEN`, a composer posts `POST …/posts {kind, body}`. It defaults to `FOLLOWUP`. The response is the whole updated `QuestionDetail`, which replaces local state, so no second fetch is needed.
   - If the thread is `CLOSED`, a "closed by course staff" note replaces the composer.

Errors: `api.ts` throws `Error(err.message)` using the backend's JSON error body. Pages show `err.message` in red text.

## Things to know before changing it

- **Duplicated code.** The `staff/` app is a near-copy of this one. `CourseContext.tsx`, `types.ts`, `utils.ts`, `components/ui/*`, `QuestionsPage.tsx`, `index.css` and the configs are identical. A change to one usually has to be repeated in the other, because nothing is shared between apps.
- **Types are written by hand.** `types.ts` mirrors `backend/app/schemas/qa.py` and is not generated. If the schema changes (for example, a new `author_role` value for AI answers), update `types.ts` and the role-badge ternary in `QuestionDetailPage.tsx`. As it stands, any role that isn't `STAFF` renders as "Student".
- **Use theme tokens, never palette classes.** Colors are semantic tokens (`bg-surface`, `text-fg-muted`, `bg-accent/15`, …), defined as CSS variables per theme in `index.css` and mapped in `tailwind.config.ts` (T8). `lib/theme.ts` and `components/ThemeToggle.tsx` handle the light/dark choice; the script in `index.html` applies it before first paint. A raw `slate-*` or `indigo-*` class would ignore the theme. See [../../docs/ui/README.md](../../docs/ui/README.md).
- **Post bodies are plain text.** They render with `whitespace-pre-wrap`: no Markdown and no link detection. A citation URL inside an AI answer won't be clickable without a change here.
- **The token is shared in production.** Behind nginx, all three apps share one origin, so they share the same `localStorage.token` and `course_id`. Logging into the staff app also logs you into this one. In dev, each app has its own port, so each has its own storage.

## Running

```bash
npm install          # once
npm run dev          # http://localhost:5173, API proxied to :8000
npm run build        # tsc -b && vite build → dist/ (mounted by nginx at /student/)
npx tsc --noEmit     # what CI runs
```
