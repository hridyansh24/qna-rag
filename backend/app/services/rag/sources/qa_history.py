"""
Historical Q&A: one chunk per thread with an accepted, non-hidden answer
(docs/design-rag.md §5.4). Q&A pairs are never split (T4).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.qa import Post, Question

ROLE_LABELS = {"STAFF": "Course Staff", "STUDENT": "Student", "AI": "AI-generated"}


@dataclass(frozen=True)
class QaThread:
    question_id: int
    title: str
    body: str
    answer_role: str
    answer_body: str

    def document(self) -> str:
        role = ROLE_LABELS.get(self.answer_role, self.answer_role)
        return (
            f"Question: {self.title}\n{self.body}\n\n"
            f"Accepted answer ({role}): {self.answer_body}"
        )


def _query(course_id: int):
    return (
        select(
            Question.id,
            Question.title,
            Question.body,
            Post.author_role,
            Post.body,
        )
        .join(Post, Post.question_id == Question.id)
        .where(
            Question.course_id == course_id,
            Post.kind == "ANSWER",
            Post.is_accepted.is_(True),
            Post.is_hidden.is_(False),
        )
        .order_by(Question.id)
    )


async def load_threads(db: AsyncSession, course_id: int) -> list[QaThread]:
    rows = await db.execute(_query(course_id))
    return [QaThread(*row) for row in rows.all()]


async def load_thread(
    db: AsyncSession, course_id: int, question_id: int
) -> QaThread | None:
    """The thread's chunk source, or None if it has no accepted, visible answer."""
    rows = await db.execute(_query(course_id).where(Question.id == question_id))
    row = rows.first()
    return QaThread(*row) if row else None
