# RAG Configuration Comparison Report

## Summary — baseline vs. each one-axis comparison

| Run | Ingestion profile | Threshold | System prompt (first 40 chars) | Generation model | Retrieval hit rate | No-match accuracy | Avg wall-clock (ms) | Avg generation (ms) | Avg CPU % |
|---|---|---|---|---|---|---|---|---|---|
| baseline | sliding-window | 0.35 | Only use the information provided in the… | qwen2.5:1.5b | 77% | 100% | 15218.0 | 15052.1 | 52.8 |
| type-tailored-chunking | type-tailored | 0.35 | Only use the information provided in the… | qwen2.5:1.5b | 77% | 100% | 10329.9 | 10190.4 | 53.5 |
| gte-qwen2-embedding | embedding-alt | 0.35 | Only use the information provided in the… | qwen2.5:1.5b | 85% | 100% | 45435.1 | 16113.5 | 27.4 |
| threshold-strict | sliding-window | 0.5 | Only use the information provided in the… | qwen2.5:1.5b | 69% | 100% | 5848.1 | 5601.2 | 53.6 |
| quote-every-claim-prompt | sliding-window | 0.35 | Only use the information provided in the… | qwen2.5:1.5b | 77% | 100% | 21791.3 | 21615.5 | 51.8 |
| context-is-data-prompt | sliding-window | 0.35 | Only use the information provided in the… | qwen2.5:1.5b | 77% | 100% | 13854.6 | 13715.5 | 53.5 |
| qwen2.5-3b-generation | sliding-window | 0.35 | Only use the information provided in the… | qwen2.5:3b | 77% | 100% | 33222.7 | 33063.3 | 50.6 |

## Per-question detail (read these to judge response quality yourself)

### q01 — baseline
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Each student has a bank of 5 slip days for the semester, usable on P1–P4 only (not the Final Project). Slip days waive the late deduction but never move the hard cutoff.
- actual answer: Each student gets a bank of 5 slip days, which can be used across P1–P4 (not the Final Project).

### q02 — baseline
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No submission is accepted more than 2 days after the due date, for any project, regardless of slip days remaining. Slip days waive the deduction within that window — they don't extend the window itself.
- actual answer: The hard cutoff for late project submissions is 2 days after the due date, regardless of slip days remaining.

### q03 — baseline
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No — quizzes and written exams are closed-AI, closed-book. Using AI on them violates the AI Use Policy.
- actual answer: No.

### q04 — baseline
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Tuesday, October 27 at 11:59 PM.
- actual answer: Project 3 is due on Tuesday, October 27 at 11:59 PM.

### q05 — baseline
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: The stack grows from 3 to 6 services — Ollama (generation), Infinity (embeddings), and ChromaDB (vector store) are the three added at Lecture 13.
- actual answer: By Lecture 13, the Docker Compose stack has 2 services. The stack originally had 1 service (FastAPI + MySQL + Redis), and Docker Compose was used to add a multi-service stack (FastAPI + MySQL + Redis + Redis Caching & Integration Testing).

### q06 — baseline
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: The parallax background scrolling system is broken. Background layers should scroll correctly relative to the camera and player movement: the farthest-back layer should be the smallest image and scroll slowest; the layer closest to the tiles should be the largest image and scroll fastest.
- actual answer: The Project 1 starter code does not specify what is broken.

### q07 — baseline
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Python style (ruff check backend/ scripts/), frontend type checking (tsc --noEmit on all three apps), and GitLab's built-in secret detection scan.
- actual answer: The pipeline runs checks for Python style, frontend types, and secret detection before a merge request can be approved.

### q08 — baseline
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Redis holds the ephemeral live state (current question, who has answered, scores) — fast, per-room, expires with the room. MySQL holds the permanent record — every answer is written to the database immediately.
- actual answer: Redis holds the ephemeral live state, while MySQL holds the permanent record of what happened.

### q09 — baseline
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Temperature controls how the model's probability distribution over the vocabulary gets sampled. Near 0.0 is nearly deterministic (the highest-probability token); around 0.7 is balanced with some variety while staying coherent; 1.5 and above is high randomness, more likely to go off the rails.
- actual answer: Temperature controls how a language model's output is sampled from the probability distribution over the vocabulary. 

- At temperature 0.0, the model outputs a highly deterministic result, favoring the highest-probability token.
- At temperatures between 0.0 and 0.7, the model outputs a balanced result, providing some variety while maintaining coherence.
- At temperatures above 1.5, the model outputs more random results, increasing the likelihood of going off the rails.

### q10 — baseline
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Even at temperature 0.0, the same prompt can produce slightly different output across runs on different hardware, because parallelized floating-point matrix operations aren't perfectly associative — tiny rounding differences can flip which token is technically highest-probability in a near-tie.
- actual answer: No, a language model is not fully deterministic at temperature 0.

### q11 — baseline
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Each model family trains its own tokenizer on its own vocabulary, so the same text produces a different token count on a different model — always count with the tokenizer for the model you're actually using.
- actual answer: No, a token count from one model's tokenizer does not transfer to a different model.

### q12 — baseline
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: In development it's safe to nuke the volume and start clean: docker compose down -v (removes the MySQL volume), then docker compose up --build, then docker compose run --rm backend alembic upgrade head again. Don't do this against anything with data you care about — -v is destructive.
- actual answer: In development, it's safe to nuke the volume and start clean: `docker compose down -v` (removes the MySQL volume), then `docker compose up --build`, then `docker compose run --rm backend alembic upgrade head` again. Don't do this against anything with data you care about — `-v` is destructive.

### q13 — baseline
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: CLAUDE.md is prose, auto-loaded at session start, for codebase overview/conventions/behavioral rules. .claude/settings.json is structured config — permissions, hooks, environment variables. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose.
- actual answer: CLAUDE.md is prose, where you put codebase overview, conventions, and behavioral rules for Claude to read. .claude/settings.json is structured config, where permissions, hooks, and environment variables are configured. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose, not JSON.

### q14 — baseline
- matched: False (expected no-match: True)
- retrieval hit: None
- expected answer: None
- actual answer: None

### q01 — type-tailored-chunking
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Each student has a bank of 5 slip days for the semester, usable on P1–P4 only (not the Final Project). Slip days waive the late deduction but never move the hard cutoff.
- actual answer: Each student gets a bank of 5 slip days to use across P1–P4 (not the Final Project).

### q02 — type-tailored-chunking
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No submission is accepted more than 2 days after the due date, for any project, regardless of slip days remaining. Slip days waive the deduction within that window — they don't extend the window itself.
- actual answer: The hard cutoff for late project submissions is 2 days after the due date, regardless of slip days remaining. Slip days waive the deduction within that 2-day window but do not extend the window itself.

### q03 — type-tailored-chunking
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No — quizzes and written exams are closed-AI, closed-book. Using AI on them violates the AI Use Policy.
- actual answer: No.

### q04 — type-tailored-chunking
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Tuesday, October 27 at 11:59 PM.
- actual answer: Project 3 is due on Tuesday, October 27 at 11:59 PM.

### q05 — type-tailored-chunking
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: The stack grows from 3 to 6 services — Ollama (generation), Infinity (embeddings), and ChromaDB (vector store) are the three added at Lecture 13.
- actual answer: By Lecture 13, the Docker Compose stack has grown from 3 to 6 services. The services added include Ollama, Infinity, and ChromaDB.

### q06 — type-tailored-chunking
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: The parallax background scrolling system is broken. Background layers should scroll correctly relative to the camera and player movement: the farthest-back layer should be the smallest image and scroll slowest; the layer closest to the tiles should be the largest image and scroll fastest.
- actual answer: The Project 1 starter code does not specify what is broken.

### q07 — type-tailored-chunking
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Python style (ruff check backend/ scripts/), frontend type checking (tsc --noEmit on all three apps), and GitLab's built-in secret detection scan.
- actual answer: Every merged MR passed the full pipeline.

### q08 — type-tailored-chunking
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Redis holds the ephemeral live state (current question, who has answered, scores) — fast, per-room, expires with the room. MySQL holds the permanent record — every answer is written to the database immediately.
- actual answer: Redis holds the ephemeral live state, while MySQL holds the permanent record.

### q09 — type-tailored-chunking
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Temperature controls how the model's probability distribution over the vocabulary gets sampled. Near 0.0 is nearly deterministic (the highest-probability token); around 0.7 is balanced with some variety while staying coherent; 1.5 and above is high randomness, more likely to go off the rails.
- actual answer: Temperature controls how a language model's probability distribution over the vocabulary is sampled. At a temperature of 0.0, the model outputs a highly deterministic result, favoring the highest-probability token. At a temperature of 1.5 or higher, the model outputs a more random result, increasing the likelihood of going off the rails.

### q10 — type-tailored-chunking
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Even at temperature 0.0, the same prompt can produce slightly different output across runs on different hardware, because parallelized floating-point matrix operations aren't perfectly associative — tiny rounding differences can flip which token is technically highest-probability in a near-tie.
- actual answer: No, a language model is not fully deterministic at temperature 0.

### q11 — type-tailored-chunking
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Each model family trains its own tokenizer on its own vocabulary, so the same text produces a different token count on a different model — always count with the tokenizer for the model you're actually using.
- actual answer: No, a token count from one model's tokenizer does not transfer to a different model.

### q12 — type-tailored-chunking
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: In development it's safe to nuke the volume and start clean: docker compose down -v (removes the MySQL volume), then docker compose up --build, then docker compose run --rm backend alembic upgrade head again. Don't do this against anything with data you care about — -v is destructive.
- actual answer: In development, it's safe to nuke the volume and start clean: `docker compose down -v` (removes the MySQL volume), then `docker compose up --build`, then `docker compose run --rm backend alembic upgrade head` again. Don't do this against anything with data you care about — `-v` is destructive.

### q13 — type-tailored-chunking
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: CLAUDE.md is prose, auto-loaded at session start, for codebase overview/conventions/behavioral rules. .claude/settings.json is structured config — permissions, hooks, environment variables. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose.
- actual answer: CLAUDE.md is prose, where you put codebase overview, conventions, and behavioral rules for Claude to read. .claude/settings.json is structured config, where permissions, hooks, and environment variables are configured. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose, not JSON.

### q14 — type-tailored-chunking
- matched: False (expected no-match: True)
- retrieval hit: None
- expected answer: None
- actual answer: None

### q01 — gte-qwen2-embedding
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Each student has a bank of 5 slip days for the semester, usable on P1–P4 only (not the Final Project). Slip days waive the late deduction but never move the hard cutoff.
- actual answer: Each student gets a bank of 5 slip days for the semester, which are usable on P1–P4 only (not the Final Project).

### q02 — gte-qwen2-embedding
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No submission is accepted more than 2 days after the due date, for any project, regardless of slip days remaining. Slip days waive the deduction within that window — they don't extend the window itself.
- actual answer: The hard cutoff for late project submissions, even if you have slip days left, is 2 days after the due date, for any project, regardless of slip days remaining.

### q03 — gte-qwen2-embedding
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No — quizzes and written exams are closed-AI, closed-book. Using AI on them violates the AI Use Policy.
- actual answer: No.

### q04 — gte-qwen2-embedding
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Tuesday, October 27 at 11:59 PM.
- actual answer: Project 3 is due on Tuesday, October 27 at 11:59 PM.

### q05 — gte-qwen2-embedding
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: The stack grows from 3 to 6 services — Ollama (generation), Infinity (embeddings), and ChromaDB (vector store) are the three added at Lecture 13.
- actual answer: By Lecture 13, the Docker Compose stack has 6 services. The stack grew from 3 services to 6 services.

### q06 — gte-qwen2-embedding
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: The parallax background scrolling system is broken. Background layers should scroll correctly relative to the camera and player movement: the farthest-back layer should be the smallest image and scroll slowest; the layer closest to the tiles should be the largest image and scroll fastest.
- actual answer: The starter code contains a planted bug (T4).

### q07 — gte-qwen2-embedding
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Python style (ruff check backend/ scripts/), frontend type checking (tsc --noEmit on all three apps), and GitLab's built-in secret detection scan.
- actual answer: The pipeline runs checks for Python style, frontend types, and secret detection before a merge request can be approved.

### q08 — gte-qwen2-embedding
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Redis holds the ephemeral live state (current question, who has answered, scores) — fast, per-room, expires with the room. MySQL holds the permanent record — every answer is written to the database immediately.
- actual answer: In Buzzer's real-time architecture, the live game state lives in Redis, while the permanent record of what happened lives in MySQL.

### q09 — gte-qwen2-embedding
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Temperature controls how the model's probability distribution over the vocabulary gets sampled. Near 0.0 is nearly deterministic (the highest-probability token); around 0.7 is balanced with some variety while staying coherent; 1.5 and above is high randomness, more likely to go off the rails.
- actual answer: Temperature controls how the probability distribution over the vocabulary is sampled. At a temperature of 0.0, the model outputs a nearly deterministic result, favoring the highest-probability token. At a temperature of 1.5 or higher, the model outputs more random results, increasing the likelihood of going off the rails.

### q10 — gte-qwen2-embedding
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Even at temperature 0.0, the same prompt can produce slightly different output across runs on different hardware, because parallelized floating-point matrix operations aren't perfectly associative — tiny rounding differences can flip which token is technically highest-probability in a near-tie.
- actual answer: No, a language model is not fully deterministic at temperature 0.

### q11 — gte-qwen2-embedding
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Each model family trains its own tokenizer on its own vocabulary, so the same text produces a different token count on a different model — always count with the tokenizer for the model you're actually using.
- actual answer: No, a token count from one model's tokenizer does not transfer to a different model.

### q12 — gte-qwen2-embedding
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: In development it's safe to nuke the volume and start clean: docker compose down -v (removes the MySQL volume), then docker compose up --build, then docker compose run --rm backend alembic upgrade head again. Don't do this against anything with data you care about — -v is destructive.
- actual answer: In development, it's safe to nuke the volume and start clean: `docker compose down -v` (removes the MySQL volume), then `docker compose up --build`, then `docker compose run --rm backend alembic upgrade head` again. Don't do this against anything with data you care about — `-v` is destructive.

### q13 — gte-qwen2-embedding
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: CLAUDE.md is prose, auto-loaded at session start, for codebase overview/conventions/behavioral rules. .claude/settings.json is structured config — permissions, hooks, environment variables. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose.
- actual answer: CLAUDE.md is prose, where you put codebase overview, conventions, and behavioral rules for Claude to read. .claude/settings.json is structured config, where permissions, hooks, and environment variables are configured. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose, not JSON.

### q14 — gte-qwen2-embedding
- matched: False (expected no-match: True)
- retrieval hit: None
- expected answer: None
- actual answer: None

### q01 — threshold-strict
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Each student has a bank of 5 slip days for the semester, usable on P1–P4 only (not the Final Project). Slip days waive the late deduction but never move the hard cutoff.
- actual answer: Each student gets 5 slip days, which are only applicable to P1-P4 projects and not the Final Project. These slip days can be used to waive the late deduction for any day up to the hard cutoff of 2 days after the due date.

### q02 — threshold-strict
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No submission is accepted more than 2 days after the due date, for any project, regardless of slip days remaining. Slip days waive the deduction within that window — they don't extend the window itself.
- actual answer: The hard cutoff for late project submissions is 2 days after the due date, regardless of the number of slip days remaining.

### q03 — threshold-strict
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No — quizzes and written exams are closed-AI, closed-book. Using AI on them violates the AI Use Policy.
- actual answer: Yes, AI is allowed during exams.

### q04 — threshold-strict
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Tuesday, October 27 at 11:59 PM.
- actual answer: Project 3 is due on Tuesday, October 27 at 11:59 PM.

### q05 — threshold-strict
- matched: False (expected no-match: False)
- retrieval hit: False
- expected answer: The stack grows from 3 to 6 services — Ollama (generation), Infinity (embeddings), and ChromaDB (vector store) are the three added at Lecture 13.
- actual answer: None

### q06 — threshold-strict
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: The parallax background scrolling system is broken. Background layers should scroll correctly relative to the camera and player movement: the farthest-back layer should be the smallest image and scroll slowest; the layer closest to the tiles should be the largest image and scroll fastest.
- actual answer: The Project 1 starter code is broken.

### q07 — threshold-strict
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Python style (ruff check backend/ scripts/), frontend type checking (tsc --noEmit on all three apps), and GitLab's built-in secret detection scan.
- actual answer: The pipeline runs checks for Python style, frontend types, and secret detection before a merge request can be approved.

### q08 — threshold-strict
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Redis holds the ephemeral live state (current question, who has answered, scores) — fast, per-room, expires with the room. MySQL holds the permanent record — every answer is written to the database immediately.
- actual answer: The live game state lives in the browsers, while the permanent record of what happened lives in the backend.

### q09 — threshold-strict
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Temperature controls how the model's probability distribution over the vocabulary gets sampled. Near 0.0 is nearly deterministic (the highest-probability token); around 0.7 is balanced with some variety while staying coherent; 1.5 and above is high randomness, more likely to go off the rails.
- actual answer: Temperature controls how a language model's probability distribution over the vocabulary is sampled. At temperature 0.0, the model outputs a nearly deterministic result, favoring the highest-probability token. At temperatures above 0.7, the model introduces more variety while still maintaining coherence. Above 1.5, the model becomes highly random, with a higher likelihood of going off the rails.

### q10 — threshold-strict
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Even at temperature 0.0, the same prompt can produce slightly different output across runs on different hardware, because parallelized floating-point matrix operations aren't perfectly associative — tiny rounding differences can flip which token is technically highest-probability in a near-tie.
- actual answer: No, a language model is not fully deterministic at temperature 0.

### q11 — threshold-strict
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Each model family trains its own tokenizer on its own vocabulary, so the same text produces a different token count on a different model — always count with the tokenizer for the model you're actually using.
- actual answer: No, a token count from one model's tokenizer does not transfer to a different model.

### q12 — threshold-strict
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: In development it's safe to nuke the volume and start clean: docker compose down -v (removes the MySQL volume), then docker compose up --build, then docker compose run --rm backend alembic upgrade head again. Don't do this against anything with data you care about — -v is destructive.
- actual answer: In development, it's safe to nuke the volume and start clean: `docker compose down -v` (removes the MySQL volume), then `docker compose up --build`, then `docker compose run --rm backend alembic upgrade head` again. Don't do this against anything with data you care about — `-v` is destructive.

### q13 — threshold-strict
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: CLAUDE.md is prose, auto-loaded at session start, for codebase overview/conventions/behavioral rules. .claude/settings.json is structured config — permissions, hooks, environment variables. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose.
- actual answer: CLAUDE.md is prose, while .claude/settings.json is structured config. CLAUDE.md is auto-loaded at session start and contains codebase overview, conventions, and behavioral rules for Claude to read. .claude/settings.json contains permissions, hooks, and environment variables, and does not have a 'rules' field.

### q14 — threshold-strict
- matched: False (expected no-match: True)
- retrieval hit: None
- expected answer: None
- actual answer: None

### q01 — quote-every-claim-prompt
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Each student has a bank of 5 slip days for the semester, usable on P1–P4 only (not the Final Project). Slip days waive the late deduction but never move the hard cutoff.
- actual answer: Each student gets a bank of 5 slip days, which can be used across P1–P4 (not the Final Project). These slip days waive the late deduction but do not extend the hard cutoff for the project.

### q02 — quote-every-claim-prompt
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No submission is accepted more than 2 days after the due date, for any project, regardless of slip days remaining. Slip days waive the deduction within that window — they don't extend the window itself.
- actual answer: The hard cutoff for late project submissions, even if you have slip days left, is 2 days after the due date, for any project, regardless of slip days remaining.

### q03 — quote-every-claim-prompt
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No — quizzes and written exams are closed-AI, closed-book. Using AI on them violates the AI Use Policy.
- actual answer: No, AI is not allowed during exams.

### q04 — quote-every-claim-prompt
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Tuesday, October 27 at 11:59 PM.
- actual answer: Project 3 is due on Tuesday, October 27 at 11:59 PM.

### q05 — quote-every-claim-prompt
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: The stack grows from 3 to 6 services — Ollama (generation), Infinity (embeddings), and ChromaDB (vector store) are the three added at Lecture 13.
- actual answer: By Lecture 13, the Docker Compose stack has 4 services. The services added include FastAPI, MySQL, Redis, and a Redis cache.

### q06 — quote-every-claim-prompt
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: The parallax background scrolling system is broken. Background layers should scroll correctly relative to the camera and player movement: the farthest-back layer should be the smallest image and scroll slowest; the layer closest to the tiles should be the largest image and scroll fastest.
- actual answer: The Project 1 starter code has a few issues that students need to fix. The first issue is that the `index.html` file is missing the `script` tag that includes the `p1-side-scroller` script. The second issue is that the `index.html` file is missing the `style` tag that includes the `p1-side-scroller` stylesheet. The third issue is that the `index.html` file is missing the `script` tag that includes the `p1-side-scroller` script. The fourth issue is that the `index.html` file is missing the `style` tag that includes the `p1-side-scroller` stylesheet. The fifth issue is that the `index.html` file is missing the `script` tag that includes the `p1-side-scroller` script. The sixth issue is that the `index.html` file is missing the `style` tag that includes the `p1-side-scroller` stylesheet. The seventh issue is that the `index.html` file is missing the `script` tag that includes the `p1-side-scroller` script. The eighth issue is that the `index.html` file is missing the `style` tag that includes the `p1-side-scroller` stylesheet. The ninth issue is that the `index.html` file is missing the `script` tag that includes the `p1-side-scroller` script. The tenth issue is that the `index.html` file is missing the `style` tag that includes the `p1-side-scroller` stylesheet. The eleventh issue is that the `index.html` file is missing the `script` tag that includes the `p1-side-scroller` script. The twelfth issue is that the `index.html` file is missing the `style` tag that includes the `p1-side-scroller` stylesheet. The thirteenth issue is that the `index.html` file is missing the `script` tag that includes the `p1-side-scroller` script. The fourteenth issue is that the `index.html` file is missing the `style` tag that includes the `p1-side-scroller` stylesheet. The fifteenth issue is that the `index.html` file is missing the `script` tag that includes the `p1-side-scroller` script. The sixteenth issue is that the `index.html` file is missing the `style` tag that includes the `p1-side-scroller` stylesheet. The seventeenth issue is that the `index

### q07 — quote-every-claim-prompt
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Python style (ruff check backend/ scripts/), frontend type checking (tsc --noEmit on all three apps), and GitLab's built-in secret detection scan.
- actual answer: The pipeline runs checks for Python style, frontend types, and secret detection before a merge request can be approved.

### q08 — quote-every-claim-prompt
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Redis holds the ephemeral live state (current question, who has answered, scores) — fast, per-room, expires with the room. MySQL holds the permanent record — every answer is written to the database immediately.
- actual answer: In Buzzer's real-time architecture, the live game state lives in Redis, while the permanent record of what happened lives in MySQL.

### q09 — quote-every-claim-prompt
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Temperature controls how the model's probability distribution over the vocabulary gets sampled. Near 0.0 is nearly deterministic (the highest-probability token); around 0.7 is balanced with some variety while staying coherent; 1.5 and above is high randomness, more likely to go off the rails.
- actual answer: Temperature controls how a language model's output is sampled from a probability distribution. At a temperature of 0.0, the model outputs a highly deterministic result, favoring the highest-probability token. At temperatures above 1.5, the model's output becomes more random, with a higher likelihood of producing tokens that are not guaranteed to be the highest probability but are still coherent and plausible.

### q10 — quote-every-claim-prompt
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Even at temperature 0.0, the same prompt can produce slightly different output across runs on different hardware, because parallelized floating-point matrix operations aren't perfectly associative — tiny rounding differences can flip which token is technically highest-probability in a near-tie.
- actual answer: No, a language model is not fully deterministic at temperature 0. The passage states: "Temperature 0.0 Isn't Fully Deterministic" and provides an explanation for why this is the case: "Even at temperature 0.0, the same prompt can produce slightly different output across runs on different hardware. " This indicates that while the model is not completely random, it can still produce slightly different outputs based on the hardware used, which is why it's not fully deterministic.

### q11 — quote-every-claim-prompt
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Each model family trains its own tokenizer on its own vocabulary, so the same text produces a different token count on a different model — always count with the tokenizer for the model you're actually using.
- actual answer: No, a token count from one model's tokenizer does not transfer to a different model. The passage states: "Each model family trains its own tokenizer on its own vocabulary — the same text produces a different token count on a different model."

### q12 — quote-every-claim-prompt
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: In development it's safe to nuke the volume and start clean: docker compose down -v (removes the MySQL volume), then docker compose up --build, then docker compose run --rm backend alembic upgrade head again. Don't do this against anything with data you care about — -v is destructive.
- actual answer: In development, it's safe to nuke the volume and start clean: `docker compose down -v` (removes the MySQL volume), then `docker compose up --build`, then `docker compose run --rm backend alembic upgrade head` again. Don't do this against anything with data you care about — `-v` is destructive.

### q13 — quote-every-claim-prompt
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: CLAUDE.md is prose, auto-loaded at session start, for codebase overview/conventions/behavioral rules. .claude/settings.json is structured config — permissions, hooks, environment variables. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose.
- actual answer: CLAUDE.md is prose, where you put codebase overview, conventions, and behavioral rules for Claude to read. .claude/settings.json is structured config, where permissions, hooks, and environment variables are configured. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose, not JSON.

### q14 — quote-every-claim-prompt
- matched: False (expected no-match: True)
- retrieval hit: None
- expected answer: None
- actual answer: None

### q01 — context-is-data-prompt
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Each student has a bank of 5 slip days for the semester, usable on P1–P4 only (not the Final Project). Slip days waive the late deduction but never move the hard cutoff.
- actual answer: Each student gets a bank of 5 slip days, which can be used across P1–P4 (not the Final Project).

### q02 — context-is-data-prompt
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No submission is accepted more than 2 days after the due date, for any project, regardless of slip days remaining. Slip days waive the deduction within that window — they don't extend the window itself.
- actual answer: No submission is accepted more than 2 days after the due date, for any project, regardless of slip days remaining.

### q03 — context-is-data-prompt
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No — quizzes and written exams are closed-AI, closed-book. Using AI on them violates the AI Use Policy.
- actual answer: No.

### q04 — context-is-data-prompt
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Tuesday, October 27 at 11:59 PM.
- actual answer: Project 3 is due on Tuesday, October 27 at 11:59 PM.

### q05 — context-is-data-prompt
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: The stack grows from 3 to 6 services — Ollama (generation), Infinity (embeddings), and ChromaDB (vector store) are the three added at Lecture 13.
- actual answer: By Lecture 13, the Docker Compose stack has 3 services. The services added are FastAPI, MySQL, and Redis.

### q06 — context-is-data-prompt
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: The parallax background scrolling system is broken. Background layers should scroll correctly relative to the camera and player movement: the farthest-back layer should be the smallest image and scroll slowest; the layer closest to the tiles should be the largest image and scroll fastest.
- actual answer: The Project 1 starter code has a problem with the `npm run test` command. The `npm run test` command is not defined in the starter code, so students will need to add it to their `package.json` file.

### q07 — context-is-data-prompt
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Python style (ruff check backend/ scripts/), frontend type checking (tsc --noEmit on all three apps), and GitLab's built-in secret detection scan.
- actual answer: The pipeline runs checks for Python style, frontend types, and secret detection.

### q08 — context-is-data-prompt
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Redis holds the ephemeral live state (current question, who has answered, scores) — fast, per-room, expires with the room. MySQL holds the permanent record — every answer is written to the database immediately.
- actual answer: Redis holds the ephemeral live state; MySQL holds the permanent record.

### q09 — context-is-data-prompt
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Temperature controls how the model's probability distribution over the vocabulary gets sampled. Near 0.0 is nearly deterministic (the highest-probability token); around 0.7 is balanced with some variety while staying coherent; 1.5 and above is high randomness, more likely to go off the rails.
- actual answer: Temperature controls how a language model's probability distribution over the vocabulary is sampled. At a temperature of 0.0, the model outputs a highly deterministic result, favoring the highest-probability token. At a temperature of 1.5 or higher, the model outputs a more random result, increasing the likelihood of the model going off the rails.

### q10 — context-is-data-prompt
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Even at temperature 0.0, the same prompt can produce slightly different output across runs on different hardware, because parallelized floating-point matrix operations aren't perfectly associative — tiny rounding differences can flip which token is technically highest-probability in a near-tie.
- actual answer: No, a language model is not fully deterministic at temperature 0.

### q11 — context-is-data-prompt
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Each model family trains its own tokenizer on its own vocabulary, so the same text produces a different token count on a different model — always count with the tokenizer for the model you're actually using.
- actual answer: No, a token count from one model's tokenizer does not transfer to a different model.

### q12 — context-is-data-prompt
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: In development it's safe to nuke the volume and start clean: docker compose down -v (removes the MySQL volume), then docker compose up --build, then docker compose run --rm backend alembic upgrade head again. Don't do this against anything with data you care about — -v is destructive.
- actual answer: In development, it's safe to nuke the volume and start clean: `docker compose down -v` (removes the MySQL volume), then `docker compose up --build`, then `docker compose run --rm backend alembic upgrade head` again. Don't do this against anything with data you care about — `-v` is destructive.

### q13 — context-is-data-prompt
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: CLAUDE.md is prose, auto-loaded at session start, for codebase overview/conventions/behavioral rules. .claude/settings.json is structured config — permissions, hooks, environment variables. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose.
- actual answer: CLAUDE.md is prose, where you put codebase overview, conventions, and behavioral rules for Claude to read. .claude/settings.json is structured config, where you put permissions, hooks, and environment variables. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose, not JSON.

### q14 — context-is-data-prompt
- matched: False (expected no-match: True)
- retrieval hit: None
- expected answer: None
- actual answer: None

### q01 — qwen2.5-3b-generation
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Each student has a bank of 5 slip days for the semester, usable on P1–P4 only (not the Final Project). Slip days waive the late deduction but never move the hard cutoff.
- actual answer: Each student gets a bank of 5 slip days to use across P1–P4 (not the Final Project).

### q02 — qwen2.5-3b-generation
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No submission is accepted more than 2 days after the due date, for any project, regardless of slip days remaining. Slip days waive the deduction within that window — they don't extend the window itself.
- actual answer: The hard cutoff for late project submissions is that no submission is accepted more than 2 days after the due date, for any project, regardless of slip days remaining.

### q03 — qwen2.5-3b-generation
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No — quizzes and written exams are closed-AI, closed-book. Using AI on them violates the AI Use Policy.
- actual answer: Yes, AI is allowed in this course, but it must be used in a way that demonstrates understanding and can be explained, defended, and verified. Using AI on quizzes or written exams is not allowed.

### q04 — qwen2.5-3b-generation
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Tuesday, October 27 at 11:59 PM.
- actual answer: Based on the information provided in the schedule, Project 3 (P3) is due on Tuesday, October 27 at 11:59 PM.

### q05 — qwen2.5-3b-generation
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: The stack grows from 3 to 6 services — Ollama (generation), Infinity (embeddings), and ChromaDB (vector store) are the three added at Lecture 13.
- actual answer: By Lecture 13, the Docker Compose stack has 3 services: FastAPI, MySQL, and Redis. The addition of the CLI service was mentioned in Lecture 14, which is after Lecture 13.

### q06 — qwen2.5-3b-generation
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: The parallax background scrolling system is broken. Background layers should scroll correctly relative to the camera and player movement: the farthest-back layer should be the smallest image and scroll slowest; the layer closest to the tiles should be the largest image and scroll fastest.
- actual answer: Based on the information provided in the context, there is no specific mention of what is broken in the Project 1 starter code that students have to fix. The context only provides the rubric for Project 1, which outlines the grading criteria and the points the project is worth. It does not mention any issues or problems with the starter code.

### q07 — qwen2.5-3b-generation
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Python style (ruff check backend/ scripts/), frontend type checking (tsc --noEmit on all three apps), and GitLab's built-in secret detection scan.
- actual answer: Project 2's CI pipeline runs the following checks before a merge request can be approved:

1. Python style
2. Frontend types
3. Secret detection

### q08 — qwen2.5-3b-generation
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Redis holds the ephemeral live state (current question, who has answered, scores) — fast, per-room, expires with the room. MySQL holds the permanent record — every answer is written to the database immediately.
- actual answer: In Buzzer's real-time architecture, the live game state lives in Redis, while the permanent record of what happened is held in MySQL.

### q09 — qwen2.5-3b-generation
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Temperature controls how the model's probability distribution over the vocabulary gets sampled. Near 0.0 is nearly deterministic (the highest-probability token); around 0.7 is balanced with some variety while staying coherent; 1.5 and above is high randomness, more likely to go off the rails.
- actual answer: Temperature in a language model controls how its probability distribution over the vocabulary is sampled. At temperature 0.0, the model's output is nearly deterministic, meaning it will always choose the highest-probability token for each input. This is because at this temperature, the model's output is not influenced by randomness, and thus it will always select the most likely next token. 

As temperature increases above 0.0, the model's output becomes more varied and less deterministic. Near temperature 0.0, the model's output is still highly deterministic, but as temperature increases, the model starts to sample from a broader range of possible outputs, leading to more varied and potentially less coherent results. 

Above temperature 1.5, the model's output becomes significantly more random and unpredictable. At this point, the model is more likely to choose less probable tokens, leading to a higher risk of generating outputs that are not grounded in the input text or the model's training data. This is why hallucinations, or outputs that are not grounded in the input or training data, become more likely at higher temperatures.

### q10 — qwen2.5-3b-generation
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Even at temperature 0.0, the same prompt can produce slightly different output across runs on different hardware, because parallelized floating-point matrix operations aren't perfectly associative — tiny rounding differences can flip which token is technically highest-probability in a near-tie.
- actual answer: No, a language model is not fully deterministic at temperature 0. While the model is nearly deterministic at temperature 0.0, slight variations can occur due to rounding differences in parallelized floating-point matrix operations, even on the same hardware.

### q11 — qwen2.5-3b-generation
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Each model family trains its own tokenizer on its own vocabulary, so the same text produces a different token count on a different model — always count with the tokenizer for the model you're actually using.
- actual answer: No, a token count from one model's tokenizer does not transfer to a different model. The context states that "Each model family trains its own tokenizer on its own vocabulary — the same text produces a different token count on a different model."

### q12 — qwen2.5-3b-generation
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: In development it's safe to nuke the volume and start clean: docker compose down -v (removes the MySQL volume), then docker compose up --build, then docker compose run --rm backend alembic upgrade head again. Don't do this against anything with data you care about — -v is destructive.
- actual answer: The safe way to reset your migrations in a bad state in development, according to the provided context, is to nuke the volume and start clean. Specifically, you would use the command `docker compose down -v` to remove the MySQL volume, then `docker compose up --build` to recreate the environment, and finally `docker compose run --rm backend alembic upgrade head` to apply the migrations again. This approach is recommended for development environments where you don't want to lose any data.

### q13 — qwen2.5-3b-generation
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: CLAUDE.md is prose, auto-loaded at session start, for codebase overview/conventions/behavioral rules. .claude/settings.json is structured config — permissions, hooks, environment variables. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose.
- actual answer: CLAUDE.md is used for prose configuration, where you can put codebase overview, conventions, and behavioral rules for Claude to read. On the other hand, .claude/settings.json is for structured configuration. It includes permissions (allow/deny specific tools or commands), hooks, and environment variables. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose.

### q14 — qwen2.5-3b-generation
- matched: False (expected no-match: True)
- retrieval hit: None
- expected answer: None
- actual answer: None
