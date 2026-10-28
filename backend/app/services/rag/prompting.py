"""
Prompt construction for the query pipeline (docs/design-rag.md §8.1–§8.3).

- context(): retrieved chunks wrapped in one tag per resource type, with
  every attribute taken from the chunk's stored metadata and no URLs.
- fit_prompt(): keeps system prompt + context + question inside the model's
  context window, dropping the lowest-ranked chunks first.
- is_sentinel(): whether an answer is the auto-responder's decline.

Pure functions only; nothing here touches the database or the services.
"""

from __future__ import annotations

import re
from xml.sax.saxutils import quoteattr

from ...common.exceptions import RagError
from ...config import settings

# T5's required guardrail, verbatim. The graded baseline uses it as is.
BASELINE_GUARDRAIL = (
    "Only use the information provided in the tagged context to answer "
    "questions. If the context does not contain enough information to answer, "
    "say so rather than guessing."
)
SENTINEL = "INSUFFICIENT_CONTEXT"
# The auto-responder's default (§8.3): the guardrail plus the sentinel.
AUTO_RESPONDER_PROMPT = (
    BASELINE_GUARDRAIL + " If the context does not contain enough information, "
    f"reply with exactly {SENTINEL} and nothing else."
)
TRUNCATION_MARKER = "\n\n[truncated: time budget reached]"

NUM_CTX = 4096
# Estimated at 3 characters per token, which errs on the safe side (§8.1).
CHARS_PER_TOKEN = 3
QUESTION_CHARS = 2000
CHUNK_CHARS = 2000

TAG_NAMES = ("syllabus", "schedule", "repo_markdown", "repo_pdf", "qa_thread")
_OUR_TAGS = re.compile(
    r"<(?=/?(?:context|" + "|".join(TAG_NAMES) + r")\b)", re.IGNORECASE
)
_SENTINEL_RE = re.compile(r"insufficient[\s_]context", re.IGNORECASE)
_SENTINEL_STRIP = str.maketrans("", "", "`\"'*")


def prompt_budget_chars() -> int:
    return (NUM_CTX - settings.OLLAMA_NUM_PREDICT) * CHARS_PER_TOKEN


def escape_text(text: str) -> str:
    """Neutralize anything that could open or close one of our tags."""
    return _OUR_TAGS.sub("&lt;", text)


def _attrs(meta: dict) -> str:
    kind = meta.get("resource_type")
    display = str(meta.get("display_name", ""))
    if kind in ("syllabus", "schedule"):
        pairs = [("source", display), ("section", meta.get("section", ""))]
    elif kind == "repo_markdown":
        pairs = [
            ("source", f"{display}: {meta.get('rel_path', '')}"),
            ("lines", f"{meta.get('line_start')}-{meta.get('line_end')}"),
        ]
    elif kind == "repo_pdf":
        pairs = [
            ("source", f"{display}: {meta.get('rel_path', '')}"),
            ("page", meta.get("page", "")),
        ]
    else:
        pairs = [("question_id", meta.get("question_id", ""))]
    return " ".join(f"{k}={quoteattr(str(v))}" for k, v in pairs)


def chunk_block(text: str, meta: dict) -> str:
    kind = meta.get("resource_type")
    tag = kind if kind in TAG_NAMES else "qa_thread"
    body = escape_text(text[:CHUNK_CHARS])
    return f"<{tag} {_attrs(meta)}>\n{body}\n</{tag}>"


def user_message(blocks: list[str], question: str) -> str:
    context = "\n".join(blocks)
    return f"<context>\n{context}\n</context>\n\nQuestion: {question[:QUESTION_CHARS]}"


def fit_prompt(system_prompt: str, chunks: list, question: str) -> tuple[list, str]:
    """
    `chunks` are best first, each with `.text` and `.metadata`. Returns the
    chunks that made it into the prompt and the user message. Raises 422 if
    not even the top chunk fits beside the system prompt.
    """
    budget = prompt_budget_chars()
    blocks = [chunk_block(c.text, c.metadata) for c in chunks]
    keep = len(blocks)
    while keep > 0:
        msg = user_message(blocks[:keep], question)
        if len(system_prompt) + len(msg) <= budget:
            return list(chunks[:keep]), msg
        keep -= 1
    raise RagError(
        "system_prompt is too long for the model's context window",
        422,
        "PROMPT_TOO_LONG",
    )


def is_sentinel(answer: str | None) -> bool:
    """A decline, however the small model quoted, cased or prefixed it (§8.3)."""
    if not answer:
        return False
    return bool(_SENTINEL_RE.search(answer.translate(_SENTINEL_STRIP)))
