# UI screenshots (T8)

Before: the starter UI, which had one dark theme built from raw `slate`/`indigo` utilities.
After: the semantic token theme, in light and dark.

All shots come from the local dev stack (course 47, the eval sample data) at 1280 px wide.
The source-viewer shots are viewport-sized and centred on the highlighted citation; the rest are full-page.

## What changed

- **Tokens.** Each app's `src/index.css` defines semantic CSS variables (`canvas`, `surface`, `fg`, `fg-muted`, `accent`, `success`, `warning`, `danger`, `ai`, `highlight`, `ring`, …) once per theme. `tailwind.config.ts` maps them into Tailwind colors, so components use classes like `bg-surface` or `text-fg-muted`, and no raw palette utilities remain in the components.
- **Toggle.** Each app has a visible theme toggle: in the header (student, staff), the sidebar (admin) and the corner of every login page. The first visit follows `prefers-color-scheme`, and keeps following it until the user chooses a theme. The choice is saved in `localStorage` (`qna-theme`), and a script in `index.html` applies it before first paint, so the page never flashes the wrong theme.
- **Accessibility.** Every text token is at least 4.5:1 (WCAG 2.1 AA) on every surface it is used on, and on its own tinted badge background, in both themes; the lowest pair is 4.8:1. Every interactive element has a visible `:focus-visible` outline in the ring color. Hidden AI posts are now marked with a dashed, sunken card instead of 60% opacity, which had dropped their text below AA.
- **The T5 and T6 surfaces.** AI answers have their own `ai` token, used for the left rule on the card and the "AI-generated" badge. Citation links use the accent color. The source viewer's highlighted range uses the `highlight` token in both themes.

## Screens

### Student — login

| Before | After (light) | After (dark) |
|---|---|---|
| ![before](before/student-login.png) | ![light](after/student-login-light.png) | ![dark](after/student-login-dark.png) |

### Student — question list

| Before | After (light) | After (dark) |
|---|---|---|
| ![before](before/student-questions.png) | ![light](after/student-questions-light.png) | ![dark](after/student-questions-dark.png) |

### Student — AI answer with citations

| Before | After (light) | After (dark) |
|---|---|---|
| ![before](before/student-question-ai-answer.png) | ![light](after/student-question-ai-answer-light.png) | ![dark](after/student-question-ai-answer-dark.png) |

### Student — ask a question

| Before | After (light) | After (dark) |
|---|---|---|
| ![before](before/student-ask.png) | ![light](after/student-ask-light.png) | ![dark](after/student-ask-dark.png) |

### Student — cited source, highlighted

| Before | After (light) | After (dark) |
|---|---|---|
| ![before](before/student-source-viewer.png) | ![light](after/student-source-viewer-light.png) | ![dark](after/student-source-viewer-dark.png) |

### Staff — login

| Before | After (light) | After (dark) |
|---|---|---|
| ![before](before/staff-login.png) | ![light](after/staff-login-light.png) | ![dark](after/staff-login-dark.png) |

### Staff — question list

| Before | After (light) | After (dark) |
|---|---|---|
| ![before](before/staff-questions.png) | ![light](after/staff-questions-light.png) | ![dark](after/staff-questions-dark.png) |

### Staff — AI answer with hide / verify

| Before | After (light) | After (dark) |
|---|---|---|
| ![before](before/staff-question-ai-answer.png) | ![light](after/staff-question-ai-answer-light.png) | ![dark](after/staff-question-ai-answer-dark.png) |

### Staff — cited source, highlighted

| Before | After (light) | After (dark) |
|---|---|---|
| ![before](before/staff-source-viewer.png) | ![light](after/staff-source-viewer-light.png) | ![dark](after/staff-source-viewer-dark.png) |

### Staff — categories

| Before | After (light) | After (dark) |
|---|---|---|
| ![before](before/staff-categories.png) | ![light](after/staff-categories-light.png) | ![dark](after/staff-categories-dark.png) |

### Staff — Resources (new in step 8, so no before shot)

| After (light) | After (dark) |
|---|---|
| ![light](after/staff-resources-light.png) | ![dark](after/staff-resources-dark.png) |

### Admin — login

| Before | After (light) | After (dark) |
|---|---|---|
| ![before](before/admin-login.png) | ![light](after/admin-login-light.png) | ![dark](after/admin-login-dark.png) |

### Admin — courses

| Before | After (light) | After (dark) |
|---|---|---|
| ![before](before/admin-courses.png) | ![light](after/admin-courses-light.png) | ![dark](after/admin-courses-dark.png) |

### Admin — users

| Before | After (light) | After (dark) |
|---|---|---|
| ![before](before/admin-users.png) | ![light](after/admin-users-light.png) | ![dark](after/admin-users-dark.png) |

### Admin — user detail

| Before | After (light) | After (dark) |
|---|---|---|
| ![before](before/admin-user-detail.png) | ![light](after/admin-user-detail-light.png) | ![dark](after/admin-user-detail-dark.png) |

### Admin — roster & staff

| Before | After (light) | After (dark) |
|---|---|---|
| ![before](before/admin-roster.png) | ![light](after/admin-roster-light.png) | ![dark](after/admin-roster-dark.png) |
