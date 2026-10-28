"""
Board-side RAG work (docs/design-rag.md §6, §7.6, §8.1, §9.5): resolving a
profile for the query pipeline, the course's live RAG settings, and the
background work that runs after a request commits: the auto-responder and
the Q&A re-index.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..common.exceptions import RagError
from ..config import settings
from ..database import AsyncSessionLocal
from ..models.qa import Post, PostCitation, Question
from ..models.resource import (
    CourseRagSettings,
    CourseResource,
    IngestionProfile,
    IngestionRun,
)
from ..models.user import User
from ..schemas.rag import RagSettings
from .auth_service import AI_USERNAME
from .rag import citations, ingestion, pipeline, prompting
from .rag.chunking import qa_chunk_id
from .rag.clients import get_chroma, get_ollama
from .rag.sources import qa_history

logger = structlog.get_logger()


async def load_profile_spec(
    db: AsyncSession, course_id: int, name: str
) -> pipeline.ProfileSpec:
    """Read-only. Always raises rather than returning None (§8.1)."""
    profile = await db.scalar(
        select(IngestionProfile).where(
            IngestionProfile.course_id == course_id, IngestionProfile.name == name
        )
    )
    if profile is None:
        raise RagError("Ingestion profile not found", 404, "PROFILE_NOT_FOUND")
    ingested = await db.scalar(
        select(IngestionRun.id)
        .where(
            IngestionRun.profile_id == profile.id,
            IngestionRun.status == "SUCCEEDED",
        )
        .limit(1)
    )
    if ingested is None:
        raise RagError("Profile has no ingested content", 409, "PROFILE_NOT_INGESTED")
    return pipeline.ProfileSpec(
        course_id, profile.name, profile.collection_name, profile.embedding_model
    )


# ---------------------------------------------------------------------------
# Live settings (§4.1, §9.5). /rag/compare never reads these.
# ---------------------------------------------------------------------------


def _settings_dict(row: CourseRagSettings) -> dict:
    return {
        "enabled": row.enabled,
        "active_profile": row.active_profile,
        "similarity_threshold": row.similarity_threshold,
        "system_prompt": row.system_prompt,
        "generation_model": row.generation_model,
    }


async def get_settings_row(db: AsyncSession, course_id: int) -> CourseRagSettings:
    """The course's row, created with the config defaults on first use."""
    row = await db.get(CourseRagSettings, course_id)
    if row is None:
        row = CourseRagSettings(
            course_id=course_id,
            enabled=True,
            active_profile=settings.RAG_DEFAULT_PROFILE,
            similarity_threshold=settings.RAG_DEFAULT_THRESHOLD,
            system_prompt=prompting.AUTO_RESPONDER_PROMPT,
            generation_model=settings.RAG_DEFAULT_MODEL,
        )
        db.add(row)
        await db.flush()
    return row


async def get_settings(db: AsyncSession, course_id: int) -> dict:
    return _settings_dict(await get_settings_row(db, course_id))


async def check_settings_model(body: RagSettings) -> RagSettings:
    """
    Normalize and check the model with Ollama before any DB query, so no
    transaction is open across the call (§3.4). 422 if it isn't pulled.
    """
    model = pipeline.normalize_model(body.generation_model)
    await get_ollama().require_model(model)
    return body.model_copy(update={"generation_model": model})


async def put_settings(db: AsyncSession, course_id: int, body: RagSettings) -> dict:
    exists = await db.scalar(
        select(IngestionProfile.id).where(
            IngestionProfile.course_id == course_id,
            IngestionProfile.name == body.active_profile,
        )
    )
    if exists is None:
        raise RagError(
            f"Ingestion profile '{body.active_profile}' does not exist in this course",
            422,
            "PROFILE_NOT_FOUND",
        )
    row = await get_settings_row(db, course_id)
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    await db.flush()
    return _settings_dict(row)


async def reindex_qa(course_id: int, question_id: int) -> None:
    """
    Keep one question's Q&A chunk current after its accepted answer changes:
    upsert it into every profile that has ingested Q&A, or delete it if the
    question no longer has an accepted, visible answer (§7.6). Never raises.
    """
    log = logger.bind(course_id=course_id, question_id=question_id)
    try:
        async with AsyncSessionLocal() as db:
            thread = await qa_history.load_thread(db, course_id, question_id)
            qa, targets = await ingestion.latest_qa_targets(db, course_id)
            qa_id, display_name = (qa.id, qa.display_name) if qa else (None, None)
        for profile, sync_id in targets:
            if thread is None:
                await get_chroma().delete(
                    profile.collection_name, ids=[qa_chunk_id(question_id)]
                )
                continue
            record = ingestion.qa_record(
                course_id, qa_id, display_name, profile.name, sync_id, thread
            )
            await ingestion.upsert_records(profile, [record])
    except Exception:  # background task; a manual Q&A sync repairs it
        log.exception("reindex_qa_failed")
        return
    log.info("reindex_qa_done", profiles=len(targets), present=thread is not None)


# ---------------------------------------------------------------------------
# The auto-responder (§6.3)
# ---------------------------------------------------------------------------


async def initial_ai_status(db: AsyncSession, course_id: int) -> str:
    """PENDING if the course's auto-responder is on, else DISABLED."""
    row = await get_settings_row(db, course_id)
    return "PENDING" if row.enabled else "DISABLED"


async def _finish(question_id: int, status: str) -> None:
    """Set a final status, never overwriting one already set (fresh session)."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Question)
            .where(Question.id == question_id, Question.ai_status == "PENDING")
            .values(ai_status=status)
        )
        await db.commit()


async def auto_answer(course_id: int, question_id: int) -> None:
    """
    Answer a new question if the course's material closely matches it.
    No DB session is open while the pipeline runs (§3.4): session A reads,
    session B writes. Never raises; a failure ends the question FAILED.
    """
    log = logger.bind(course_id=course_id, question_id=question_id)
    try:
        async with AsyncSessionLocal() as db:
            row = await get_settings_row(db, course_id)
            live = _settings_dict(row)
            await db.commit()  # only the lazy insert, if any
            if not live["enabled"]:
                await _finish(question_id, "DISABLED")
                return
            question = await db.get(Question, question_id)
            text = f"{question.title}\n\n{question.body}"
            try:
                spec = await load_profile_spec(db, course_id, live["active_profile"])
            except RagError as exc:
                if exc.status_code in (404, 409):
                    await _finish(question_id, "NOT_READY")
                    return
                raise
        try:
            result = await pipeline.answer(
                spec,
                text,
                live["similarity_threshold"],
                live["system_prompt"],
                live["generation_model"],
                priority=pipeline.Priority.AUTO,
            )
        except RagError as exc:
            if exc.status_code in (404, 409):  # the collection is gone
                await _finish(question_id, "NOT_READY")
                return
            raise
        if not result.matched:
            await _finish(question_id, "NO_MATCH")
            log.info("auto_answer_no_match")
            return
        if prompting.is_sentinel(result.answer):
            await _finish(question_id, "DECLINED")
            log.info("auto_answer_declined")
            return
        status = await create_ai_answer(question_id, result)
        log.info("auto_answer_done", ai_status=status)
    except Exception:
        log.exception("auto_answer_failed")
        try:
            await _finish(question_id, "FAILED")
        except Exception:
            log.exception("auto_answer_failed_to_record_failure")


async def create_ai_answer(question_id: int, result: pipeline.Result) -> str:
    """
    Session B (§6.3): one short transaction with locking reads, so it sees
    every staff answer or close committed before it, and holds off any that
    arrive while it runs. Returns the question's final ai_status.
    """
    async with AsyncSessionLocal() as db:
        question = await db.scalar(
            select(Question).where(Question.id == question_id).with_for_update()
        )
        if question is None or question.ai_status != "PENDING":
            return question.ai_status if question else "FAILED"
        posts = (
            await db.scalars(
                select(Post).where(Post.question_id == question_id).with_for_update()
            )
        ).all()
        if question.status == "CLOSED" or any(
            p.author_role == "AI"
            or p.is_accepted
            or (p.author_role == "STAFF" and p.kind == "ANSWER")
            for p in posts
        ):
            question.ai_status = "SKIPPED"
            await db.commit()
            return "SKIPPED"

        cites = citations.citations_for(result.prompt_chunks)
        ids = {c["resource_id"] for c in cites if c["resource_id"] is not None}
        live_ids = set()
        if ids:
            live_ids = set(
                (
                    await db.scalars(
                        select(CourseResource.id)
                        .where(CourseResource.id.in_(ids))
                        .with_for_update(read=True)
                    )
                ).all()
            )
        ai_user = await db.scalar(select(User).where(User.username == AI_USERNAME))
        post = Post(
            question_id=question_id,
            author_user_id=ai_user.id,
            author_role="AI",
            kind="ANSWER",
            body=result.answer.strip(),
        )
        db.add(post)
        await db.flush()
        for c in cites:
            if c["resource_id"] not in live_ids:
                c["resource_id"] = None
            db.add(PostCitation(post_id=post.id, **c))
        question.ai_status = "ANSWERED"
        await db.commit()
        return "ANSWERED"
