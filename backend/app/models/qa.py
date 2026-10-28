from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base

if TYPE_CHECKING:
    from .course import Course
    from .resource import CourseResource
    from .user import User

# Why a question has (or hasn't) received an AI answer. NONE means the
# question predates the feature; every other value is set by the
# auto-responder (docs/design-rag.md §4.1, §6.3).
AI_STATUSES = (
    "NONE",
    "PENDING",
    "ANSWERED",
    "NO_MATCH",
    "DECLINED",
    "DISABLED",
    "NOT_READY",
    "SKIPPED",
    "FAILED",
)


class Category(Base):
    """A staff-managed tag questions can be filed under (per course)."""

    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("course_id", "name", name="uq_category_course_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    course: Mapped[Course] = relationship("Course", back_populates="categories")
    question_links: Mapped[list[QuestionCategory]] = relationship(
        "QuestionCategory", back_populates="category", cascade="all, delete-orphan"
    )


class Question(Base):
    """The root of a Q&A thread: a student's question plus every reply."""

    __tablename__ = "questions"
    __table_args__ = (Index("ix_questions_course_status", "course_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    author_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("OPEN", "CLOSED", name="question_status"), default="OPEN", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    ai_status: Mapped[str] = mapped_column(
        Enum(*AI_STATUSES, name="question_ai_status"),
        default="NONE",
        server_default="NONE",
        nullable=False,
    )

    course: Mapped[Course] = relationship("Course", back_populates="questions")
    author: Mapped[User] = relationship(
        "User", back_populates="questions", foreign_keys=[author_user_id]
    )
    closed_by: Mapped[User | None] = relationship(
        "User", foreign_keys=[closed_by_user_id]
    )
    category_links: Mapped[list[QuestionCategory]] = relationship(
        "QuestionCategory", back_populates="question", cascade="all, delete-orphan"
    )
    posts: Mapped[list[Post]] = relationship(
        "Post",
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="Post.created_at",
    )


class QuestionCategory(Base):
    """Many-to-many: a question can carry more than one category tag."""

    __tablename__ = "question_categories"

    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True
    )

    question: Mapped[Question] = relationship(
        "Question", back_populates="category_links"
    )
    category: Mapped[Category] = relationship(
        "Category", back_populates="question_links"
    )


class Post(Base):
    """
    A single entry in a question's thread: either an ANSWER (attempts to
    resolve the question; can be marked accepted by staff regardless of who
    wrote it) or a FOLLOWUP (plain running discussion, never accepted).

    `author_role` records the capacity the author posted in. For people it
    snapshots their course role (STUDENT/STAFF) at the moment of posting, so
    a "staff answer" badge never retroactively changes if that person's
    course access is later revoked or altered. AI marks an answer written by
    the auto-responder through the `qna-assistant` system user; it is the
    only value that isn't a course role.

    `is_hidden` is set by staff on AI posts only; students never see a
    hidden post (docs/design-rag.md §6.5).
    """

    __tablename__ = "posts"
    __table_args__ = (Index("ix_posts_question_created", "question_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    author_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    author_role: Mapped[str] = mapped_column(
        Enum("STUDENT", "STAFF", "AI", name="post_author_role"), nullable=False
    )
    kind: Mapped[str] = mapped_column(
        Enum("ANSWER", "FOLLOWUP", name="post_kind"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_accepted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    accepted_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_hidden: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    question: Mapped[Question] = relationship("Question", back_populates="posts")
    author: Mapped[User] = relationship(
        "User", back_populates="posts", foreign_keys=[author_user_id]
    )
    accepted_by: Mapped[User | None] = relationship(
        "User", foreign_keys=[accepted_by_user_id]
    )
    citations: Mapped[list[PostCitation]] = relationship(
        "PostCitation",
        back_populates="post",
        cascade="all, delete-orphan",
        order_by="PostCitation.rank",
    )


class PostCitation(Base):
    """
    One source an AI answer was grounded in. The location data is copied
    from the chunk's metadata when the answer is posted, so re-syncing or
    deleting the resource never breaks an answer already on the board
    (docs/design-rag.md §4.1).
    """

    __tablename__ = "post_citations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rank: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    resource_id: Mapped[int | None] = mapped_column(
        ForeignKey("course_resources.id", ondelete="SET NULL"), nullable=True
    )
    resource_type: Mapped[str] = mapped_column(String(20), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    citation_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    location_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    quoted_text: Mapped[str] = mapped_column(Text, nullable=False)
    similarity_score: Mapped[float] = mapped_column(Float, nullable=False)

    post: Mapped[Post] = relationship("Post", back_populates="citations")
    resource: Mapped[CourseResource | None] = relationship("CourseResource")
