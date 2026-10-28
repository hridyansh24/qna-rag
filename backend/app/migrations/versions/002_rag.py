"""RAG auto-responder — resources, profiles, runs, settings, citations

Revision ID: 002
Revises: 001
Create Date: 2026-10-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

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


def upgrade() -> None:
    op.alter_column(
        "posts",
        "author_role",
        type_=sa.Enum("STUDENT", "STAFF", "AI", name="post_author_role"),
        existing_type=sa.Enum("STUDENT", "STAFF", name="post_author_role"),
        existing_nullable=False,
    )
    op.add_column(
        "posts",
        sa.Column("is_hidden", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "questions",
        sa.Column(
            "ai_status",
            sa.Enum(*AI_STATUSES, name="question_ai_status"),
            nullable=False,
            server_default="NONE",
        ),
    )

    op.create_table(
        "course_resources",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "course_id",
            sa.Integer,
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "resource_type",
            sa.Enum(
                "SYLLABUS", "SCHEDULE", "REPOSITORY", "QA_HISTORY", name="resource_type"
            ),
            nullable=False,
        ),
        sa.Column(
            "source_kind",
            sa.Enum("URL", "UPLOAD", "BOARD", name="resource_source_kind"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("url", sa.String(2048), nullable=True),
        sa.Column("repo_ref", sa.String(255), nullable=True),
        sa.Column("upload_source_path", sa.String(512), nullable=True),
        sa.Column("last_commit_sha", sa.String(40), nullable=True),
        sa.Column(
            "qa_history_key",
            sa.SmallInteger,
            sa.Computed("IF(resource_type = 'QA_HISTORY', 1, NULL)", persisted=True),
        ),
        sa.Column(
            "created_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime, nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "course_id", "qa_history_key", name="uq_resource_qa_history"
        ),
    )

    op.create_table(
        "ingestion_profiles",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "course_id",
            sa.Integer,
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("embedding_model", sa.String(255), nullable=False),
        sa.Column("chunking_json", sa.JSON, nullable=False),
        sa.Column("collection_name", sa.String(63), nullable=False),
        sa.Column(
            "created_at", sa.DateTime, nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("course_id", "name", name="uq_profile_course_name"),
    )

    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "course_id",
            sa.Integer,
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "profile_id",
            sa.Integer,
            sa.ForeignKey("ingestion_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "resource_id",
            sa.Integer,
            sa.ForeignKey("course_resources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "QUEUED", "RUNNING", "SUCCEEDED", "FAILED", name="ingestion_run_status"
            ),
            nullable=False,
        ),
        sa.Column("sync_id", sa.String(32), nullable=False),
        sa.Column("chunk_count", sa.Integer, nullable=True),
        sa.Column("commit_sha", sa.String(40), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("skipped_json", sa.JSON, nullable=True),
        sa.Column(
            "created_at", sa.DateTime, nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("finished_at", sa.DateTime, nullable=True),
    )
    op.create_index(
        "ix_runs_resource_profile", "ingestion_runs", ["resource_id", "profile_id"]
    )

    op.create_table(
        "course_rag_settings",
        sa.Column(
            "course_id",
            sa.Integer,
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("active_profile", sa.String(40), nullable=False),
        sa.Column("similarity_threshold", sa.Float, nullable=False),
        sa.Column("system_prompt", sa.Text, nullable=False),
        sa.Column("generation_model", sa.String(100), nullable=False),
    )

    op.create_table(
        "post_citations",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "post_id",
            sa.Integer,
            sa.ForeignKey("posts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("rank", sa.SmallInteger, nullable=False),
        sa.Column(
            "resource_id",
            sa.Integer,
            sa.ForeignKey("course_resources.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("resource_type", sa.String(20), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("citation_url", sa.String(2048), nullable=False),
        sa.Column("location_json", sa.JSON, nullable=False),
        sa.Column("quoted_text", sa.Text, nullable=False),
        sa.Column("similarity_score", sa.Float, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("post_citations")
    op.drop_table("course_rag_settings")
    op.drop_table("ingestion_runs")
    op.drop_table("ingestion_profiles")
    op.drop_table("course_resources")
    op.drop_column("questions", "ai_status")
    op.drop_column("posts", "is_hidden")
    # AI posts can't survive the narrower enum.
    op.execute("DELETE FROM posts WHERE author_role = 'AI'")
    op.alter_column(
        "posts",
        "author_role",
        type_=sa.Enum("STUDENT", "STAFF", name="post_author_role"),
        existing_type=sa.Enum("STUDENT", "STAFF", "AI", name="post_author_role"),
        existing_nullable=False,
    )
