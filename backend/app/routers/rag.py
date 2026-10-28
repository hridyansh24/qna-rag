"""
The course's live RAG settings, and POST /rag/compare, the fixed T6 contract
the comparison harness drives (docs/design-rag.md §9.1, §9.5). Staff-only;
admins pass the guard, which covers the harness.
"""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..common.dependencies import CourseMember, require_course_staff
from ..config import settings
from ..database import get_db
from ..schemas.rag import RagCompareRequest, RagCompareResponse, RagSettings
from ..services import rag_service
from ..services.rag import pipeline

router = APIRouter(tags=["rag"])

Staff = Annotated[CourseMember, Depends(require_course_staff)]
Db = Annotated[AsyncSession, Depends(get_db)]


@router.get("/courses/{course_id}/rag/settings", response_model=RagSettings)
async def get_settings(course_id: int, member: Staff, db: Db):
    return await rag_service.get_settings(db, course_id)


@router.put("/courses/{course_id}/rag/settings", response_model=RagSettings)
async def put_settings(course_id: int, body: RagSettings, member: Staff, db: Db):
    # The guard's access query opened a transaction; end it before calling
    # Ollama, so none stays open across the call (§3.4).
    await db.rollback()
    body = await rag_service.check_settings_model(body)
    return await rag_service.put_settings(db, course_id, body)


@router.post("/courses/{course_id}/rag/compare", response_model=RagCompareResponse)
async def compare(course_id: int, body: RagCompareRequest, member: Staff, db: Db):
    """
    A dry run: nothing is added or flushed, so get_db's closing commit has
    nothing to write. The read transaction ends before the pipeline runs.
    """
    arrival = time.monotonic()
    spec = await rag_service.load_profile_spec(db, course_id, body.ingestion_profile)
    await db.rollback()
    result = await pipeline.answer(
        spec,
        body.question,
        body.similarity_threshold,
        body.system_prompt,
        body.generation_model,
        priority=pipeline.Priority.COMPARE,
        deadline=arrival + settings.COMPARE_BUDGET_S,
    )
    return {
        "matched": result.matched,
        "retrieved_chunks": [
            {
                "resource_type": c.metadata.get("resource_type", ""),
                "source_url": c.metadata.get("source_url", ""),
                "similarity_score": round(c.similarity, 4),
                "text": c.text,
            }
            for c in result.chunks
        ],
        "answer": result.answer,
        "metrics": result.metrics,
    }
