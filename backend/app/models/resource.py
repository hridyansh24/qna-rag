from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Computed,
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
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base

RESOURCE_TYPES = ("SYLLABUS", "SCHEDULE", "REPOSITORY", "QA_HISTORY")
SOURCE_KINDS = ("URL", "UPLOAD", "BOARD")
RUN_STATUSES = ("QUEUED", "RUNNING", "SUCCEEDED", "FAILED")


class CourseResource(Base):
    """
    A registered source of course material: a syllabus or schedule page, a
    repository, or the course's own historical Q&A. Exactly one QA_HISTORY
    row exists per course, enforced by the unique index over the generated
    `qa_history_key` column (NULL for every other type, and MySQL lets NULLs
    repeat in a unique index). See docs/design-rag.md §4.1.
    """

    __tablename__ = "course_resources"
    __table_args__ = (
        UniqueConstraint("course_id", "qa_history_key", name="uq_resource_qa_history"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resource_type: Mapped[str] = mapped_column(
        Enum(*RESOURCE_TYPES, name="resource_type"), nullable=False
    )
    source_kind: Mapped[str] = mapped_column(
        Enum(*SOURCE_KINDS, name="resource_source_kind"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    repo_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    upload_source_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    qa_history_key: Mapped[int | None] = mapped_column(
        SmallInteger,
        Computed("IF(resource_type = 'QA_HISTORY', 1, NULL)", persisted=True),
    )
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class IngestionProfile(Base):
    """
    A named, immutable ingestion configuration: the embedding model plus a
    fallback chunker per resource type. Each profile has its own Chroma
    collection. There is no edit or delete; different settings mean a new
    profile name.
    """

    __tablename__ = "ingestion_profiles"
    __table_args__ = (
        UniqueConstraint("course_id", "name", name="uq_profile_course_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    chunking_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    collection_name: Mapped[str] = mapped_column(String(63), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class IngestionRun(Base):
    """
    One sync of one resource under one profile. `sync_id` tags every chunk
    the run writes, so the run's cleanup can delete exactly the chunks it
    didn't write (docs/design-rag.md §7.5).
    """

    __tablename__ = "ingestion_runs"
    __table_args__ = (Index("ix_runs_resource_profile", "resource_id", "profile_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("ingestion_profiles.id", ondelete="CASCADE"), nullable=False
    )
    resource_id: Mapped[int] = mapped_column(
        ForeignKey("course_resources.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Enum(*RUN_STATUSES, name="ingestion_run_status"), nullable=False
    )
    sync_id: Mapped[str] = mapped_column(String(32), nullable=False)
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    skipped_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CourseRagSettings(Base):
    """
    The auto-responder's live, query-time settings for one course. Created
    lazily with defaults from config. `/rag/compare` never reads these.
    """

    __tablename__ = "course_rag_settings"

    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    active_profile: Mapped[str] = mapped_column(String(40), nullable=False)
    similarity_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    generation_model: Mapped[str] = mapped_column(String(100), nullable=False)
