"""
Course resources, ingestion profiles and runs (docs/design-rag.md §4.1,
§7.4, §7.5, §9.5).

Every request that starts a run, replaces files or deletes a resource first
locks the resource row (`SELECT … FOR UPDATE`), then checks for active runs
and writes, in one transaction, so two such requests for one resource run
one after the other and the 409 rules can't race.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import structlog
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..common.exceptions import ConflictError, NotFoundError, QnaError
from ..config import settings
from ..models.resource import CourseResource, IngestionProfile, IngestionRun
from ..models.user import User
from ..schemas.rag import ProfileCreate, ResourceCreate
from .rag import ingestion
from .rag.clients import get_chroma
from .rag.sources import uploads

logger = structlog.get_logger()

ACTIVE = ingestion.ACTIVE_STATUSES
QA_DISPLAY_NAME = "Historical Q&A"
_REPO_REF = re.compile(r"^[A-Za-z0-9._/-]{1,255}$")

MINILM = "sentence-transformers/all-MiniLM-L6-v2"
GTE_QWEN2 = "Alibaba-NLP/gte-Qwen2-1.5B-instruct"
_BASELINE = {"strategy": "sliding_window", "chunk_size": 200, "chunk_overlap": 40}
_SEMANTIC = {
    "strategy": "semantic",
    "breakpoint_percentile": 25,
    "max_tokens": 220,
    "overflow": {"chunk_size": 200, "chunk_overlap": 40},
}
# The three required profiles, named as in eval/configs.example.json (§7.4).
PRESETS = [
    {
        "name": "sliding-window",
        "embedding_model": MINILM,
        "chunking": {"default": _BASELINE},
    },
    {
        "name": "type-tailored",
        "embedding_model": MINILM,
        "chunking": {
            "default": _BASELINE,
            # 80, not 120: no slide reaches 200 tokens and only 3 of 19
            # exceed 120, so a larger window would barely run (§7.4).
            "pdf": {
                "strategy": "sliding_window",
                "chunk_size": 80,
                "chunk_overlap": 16,
            },
            "web": _SEMANTIC,
            "markdown": _SEMANTIC,
        },
    },
    {
        "name": "embedding-alt",
        "embedding_model": GTE_QWEN2,
        "chunking": {"default": _BASELINE},
    },
]


class ResourceValidationError(QnaError):
    def __init__(self, message: str):
        super().__init__("INVALID_RESOURCE", message, 422)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Serialization (§9.6)
# ---------------------------------------------------------------------------


def serialize_run(run: IngestionRun, profile_name: str) -> dict:
    return {
        "id": run.id,
        "resource_id": run.resource_id,
        "profile": profile_name,
        "status": run.status,
        "chunk_count": run.chunk_count,
        "commit_sha": run.commit_sha,
        "error": run.error,
        "skipped_files": run.skipped_json or [],
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }


def serialize_profile(profile: IngestionProfile) -> dict:
    return {
        "name": profile.name,
        "embedding_model": profile.embedding_model,
        "chunking": profile.chunking_json,
        "collection_name": profile.collection_name,
        "created_at": profile.created_at,
    }


def _stored_paths(resource: CourseResource) -> list[str]:
    if resource.source_kind != "UPLOAD":
        return []
    return [path for path, _ in uploads.iter_stored_files(resource.id)]


async def _serialize_resources(
    db: AsyncSession, course_id: int, resources: list[CourseResource]
) -> list[dict]:
    profiles = (
        await db.scalars(
            select(IngestionProfile)
            .where(IngestionProfile.course_id == course_id)
            .order_by(IngestionProfile.id)
        )
    ).all()
    names = {p.id: p.name for p in profiles}
    latest: dict[tuple[int, int], IngestionRun] = {}
    runs = await db.scalars(
        select(IngestionRun)
        .where(IngestionRun.resource_id.in_([r.id for r in resources]))
        .order_by(IngestionRun.id.desc())
    )
    for run in runs:
        latest.setdefault((run.resource_id, run.profile_id), run)
    files = await asyncio.to_thread(lambda: {r.id: _stored_paths(r) for r in resources})
    out = []
    for r in resources:
        latest_runs = {}
        for pid, name in names.items():
            run = latest.get((r.id, pid))
            latest_runs[name] = serialize_run(run, name) if run else None
        out.append(
            {
                "id": r.id,
                "resource_type": r.resource_type,
                "source_kind": r.source_kind,
                "display_name": r.display_name,
                "url": r.url,
                "repo_ref": r.repo_ref,
                "upload_source_path": r.upload_source_path,
                "files": files[r.id],
                "last_commit_sha": r.last_commit_sha,
                "created_at": r.created_at,
                "latest_runs": latest_runs,
            }
        )
    return out


async def serialize_resource(db: AsyncSession, resource: CourseResource) -> dict:
    await db.refresh(resource)
    return (await _serialize_resources(db, resource.course_id, [resource]))[0]


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


async def ensure_qa_history(db: AsyncSession, course_id: int, user: User) -> None:
    """
    Create the course's QA_HISTORY row if it's missing. Call before any other
    write in the request: a losing racer's IntegrityError rolls back only
    the savepoint (§4.1).
    """
    exists = await db.scalar(
        select(CourseResource.id).where(
            CourseResource.course_id == course_id,
            CourseResource.resource_type == "QA_HISTORY",
        )
    )
    if exists:
        return
    try:
        async with db.begin_nested():
            db.add(
                CourseResource(
                    course_id=course_id,
                    resource_type="QA_HISTORY",
                    source_kind="BOARD",
                    display_name=QA_DISPLAY_NAME,
                    created_by_user_id=user.id,
                )
            )
    except IntegrityError:
        logger.info("qa_history_created_concurrently", course_id=course_id)


async def list_resources(db: AsyncSession, course_id: int, user: User) -> list[dict]:
    await ensure_qa_history(db, course_id, user)
    resources = (
        await db.scalars(
            select(CourseResource)
            .where(CourseResource.course_id == course_id)
            .order_by(CourseResource.id)
        )
    ).all()
    return await _serialize_resources(db, course_id, list(resources))


def _validate_url_resource(body: ResourceCreate) -> None:
    if body.resource_type == "QA_HISTORY":
        raise ResourceValidationError(
            "Historical Q&A is created automatically and can't be registered"
        )
    parts = urlsplit(body.url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ResourceValidationError("The URL must be an http or https URL")
    if parts.username or parts.password:
        raise ResourceValidationError("The URL must not contain a username or password")
    if body.resource_type != "REPOSITORY":
        if body.repo_ref is not None:
            raise ResourceValidationError("A branch only applies to repositories")
        return
    if parts.scheme != "https":
        raise ResourceValidationError("A repository URL must use https")
    if parts.query or parts.fragment:
        raise ResourceValidationError(
            "A repository URL must not have a query or fragment"
        )
    if parts.hostname.lower() not in settings.rag_git_hosts_list:
        raise ResourceValidationError(
            f"Repositories must be on {', '.join(settings.rag_git_hosts_list)}"
        )
    ref = body.repo_ref
    if ref is not None and (
        not _REPO_REF.match(ref) or ref.startswith("-") or ".." in ref
    ):
        raise ResourceValidationError("The branch name isn't valid")


async def register_url_resource(
    db: AsyncSession, course_id: int, user: User, body: ResourceCreate
) -> CourseResource:
    _validate_url_resource(body)
    resource = CourseResource(
        course_id=course_id,
        resource_type=body.resource_type,
        source_kind="URL",
        display_name=body.display_name.strip(),
        url=body.url,
        repo_ref=body.repo_ref,
        created_by_user_id=user.id,
    )
    db.add(resource)
    await db.flush()
    return resource


def _check_upload_type(resource_type: str) -> None:
    if resource_type == "QA_HISTORY":
        raise ResourceValidationError("Historical Q&A can't be uploaded")
    if resource_type not in uploads.ALLOWED_SINGLE_FILE:
        raise ResourceValidationError(f"Unknown resource type {resource_type!r}")


def _is_zip(filename: str) -> bool:
    return PurePosixPath(filename or "").suffix.lower() == ".zip"


async def create_upload(
    db: AsyncSession,
    course_id: int,
    user: User,
    resource_type: str,
    display_name: str,
    filename: str,
    content: bytes,
    source_path: str,
) -> tuple[CourseResource, uploads.UploadResult]:
    _check_upload_type(resource_type)
    display_name = display_name.strip()
    if not 1 <= len(display_name) <= 255:
        raise ResourceValidationError("Display name must be 1–255 characters")
    stored_source = uploads.normalize_source_path(
        source_path, is_directory=_is_zip(filename)
    )
    resource = CourseResource(
        course_id=course_id,
        resource_type=resource_type,
        source_kind="UPLOAD",
        display_name=display_name,
        upload_source_path=stored_source,
        created_by_user_id=user.id,
    )
    db.add(resource)
    await db.flush()  # the files live under the new row's id
    result = await asyncio.to_thread(
        uploads.store_upload, resource.id, resource_type, filename, content, source_path
    )
    return resource, result


async def _lock_resource(
    db: AsyncSession, course_id: int, resource_id: int
) -> CourseResource:
    resource = await db.scalar(
        select(CourseResource)
        .where(CourseResource.id == resource_id, CourseResource.course_id == course_id)
        .with_for_update()
    )
    if resource is None:
        raise NotFoundError(f"Resource {resource_id} not found")
    return resource


async def _has_active_run(
    db: AsyncSession, resource_id: int, profile_id: int | None = None
) -> bool:
    query = select(IngestionRun.id).where(
        IngestionRun.resource_id == resource_id, IngestionRun.status.in_(ACTIVE)
    )
    if profile_id is not None:
        query = query.where(IngestionRun.profile_id == profile_id)
    return (await db.scalar(query.limit(1))) is not None


async def replace_upload(
    db: AsyncSession,
    course_id: int,
    resource_id: int,
    filename: str,
    content: bytes,
    source_path: str,
) -> tuple[CourseResource, uploads.UploadResult]:
    """
    Swap in new files. The row lock is held until the caller commits, so a
    sync requested mid-swap waits and then reads the new files (§7.1).
    """
    resource = await _lock_resource(db, course_id, resource_id)
    if resource.source_kind != "UPLOAD":
        raise ConflictError("Only uploaded resources can have their files replaced")
    if await _has_active_run(db, resource.id):
        raise ConflictError("This resource is syncing; wait for its runs to finish")
    stored_source = uploads.normalize_source_path(
        source_path, is_directory=_is_zip(filename)
    )
    result = await asyncio.to_thread(
        uploads.replace_upload,
        resource.id,
        resource.resource_type,
        filename,
        content,
        source_path,
    )
    resource.upload_source_path = stored_source
    return resource, result


async def delete_resource(db: AsyncSession, course_id: int, resource_id: int) -> None:
    """
    Chunks first, then the row, then the files (§9.5), so a failure never
    leaves chunks of a resource that no longer exists. The row lock is held
    across the Chroma deletes on purpose: the one exception to §3.4.
    """
    resource = await _lock_resource(db, course_id, resource_id)
    if resource.resource_type == "QA_HISTORY":
        raise ConflictError("Historical Q&A can't be deleted")
    if await _has_active_run(db, resource.id):
        raise ConflictError("This resource is syncing; wait for its runs to finish")
    # A profile's collection exists once any of its runs has started.
    collections = (
        await db.scalars(
            select(IngestionProfile.collection_name)
            .where(IngestionProfile.course_id == course_id)
            .where(
                select(IngestionRun.id)
                .where(IngestionRun.profile_id == IngestionProfile.id)
                .exists()
            )
        )
    ).all()
    for name in collections:
        await get_chroma().delete(name, where={"resource_id": resource.id})
    await db.execute(delete(CourseResource).where(CourseResource.id == resource.id))
    await db.commit()
    try:
        await asyncio.to_thread(uploads.delete_stored_files, resource.id)
    except OSError:
        logger.warning("resource_files_not_removed", resource_id=resource.id)


async def stored_file(
    db: AsyncSession, course_id: int, resource_id: int, path: str
) -> Path:
    resource = await db.scalar(
        select(CourseResource).where(
            CourseResource.id == resource_id,
            CourseResource.course_id == course_id,
            CourseResource.source_kind == "UPLOAD",
        )
    )
    if resource is None:
        raise NotFoundError("File not found")
    return uploads.resolve_stored_file(resource.id, path)


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


async def get_profile(db: AsyncSession, course_id: int, name: str) -> IngestionProfile:
    profile = await db.scalar(
        select(IngestionProfile).where(
            IngestionProfile.course_id == course_id, IngestionProfile.name == name
        )
    )
    if profile is None:
        raise NotFoundError("Ingestion profile not found")
    return profile


async def list_profiles(db: AsyncSession, course_id: int) -> list[dict]:
    profiles = await db.scalars(
        select(IngestionProfile)
        .where(IngestionProfile.course_id == course_id)
        .order_by(IngestionProfile.id)
    )
    return [serialize_profile(p) for p in profiles]


async def create_profile(
    db: AsyncSession, course_id: int, user: User, body: ProfileCreate
) -> IngestionProfile:
    await ensure_qa_history(db, course_id, user)
    if body.embedding_model not in settings.rag_embedding_models_list:
        raise ResourceValidationError(
            f"Embedding model must be one of {settings.rag_embedding_models_list}"
        )
    exists = await db.scalar(
        select(IngestionProfile.id).where(
            IngestionProfile.course_id == course_id, IngestionProfile.name == body.name
        )
    )
    if exists:
        raise ConflictError(
            f"Profile '{body.name}' already exists; profiles can't be edited"
        )
    profile = IngestionProfile(
        course_id=course_id,
        name=body.name,
        embedding_model=body.embedding_model,
        chunking_json=body.chunking.model_dump(exclude_none=True),
        collection_name=f"qna_c{course_id}__{body.name}",
    )
    try:
        async with db.begin_nested():
            db.add(profile)
    except IntegrityError:
        raise ConflictError(f"Profile '{body.name}' already exists")
    await db.refresh(profile)
    return profile


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


async def start_sync(
    db: AsyncSession, course_id: int, resource_id: int, profile_name: str
) -> int:
    resource = await _lock_resource(db, course_id, resource_id)
    profile = await get_profile(db, course_id, profile_name)
    if await _has_active_run(db, resource.id, profile.id):
        raise ConflictError(
            f"'{resource.display_name}' is already syncing under '{profile.name}'"
        )
    run = IngestionRun(
        course_id=course_id,
        profile_id=profile.id,
        resource_id=resource.id,
        status="RUNNING",
        sync_id=ingestion.new_sync_id(),
        started_at=_now(),
    )
    db.add(run)
    await db.flush()
    return run.id


async def start_sync_all(
    db: AsyncSession, course_id: int, user: User, profile_name: str
) -> list[int]:
    """One QUEUED run per resource, Q&A included, run in order by one task (§7.5)."""
    await ensure_qa_history(db, course_id, user)
    profile = await get_profile(db, course_id, profile_name)
    # Lock in id order, so two sync-alls can't deadlock.
    resources = (
        await db.scalars(
            select(CourseResource)
            .where(CourseResource.course_id == course_id)
            .order_by(CourseResource.id)
            .with_for_update()
        )
    ).all()
    busy = [
        r.display_name for r in resources if await _has_active_run(db, r.id, profile.id)
    ]
    if busy:
        raise ConflictError(
            f"Already syncing under '{profile.name}': {', '.join(busy)}"
        )
    runs = [
        IngestionRun(
            course_id=course_id,
            profile_id=profile.id,
            resource_id=r.id,
            status="QUEUED",
            sync_id=ingestion.new_sync_id(),
        )
        for r in resources
    ]
    db.add_all(runs)
    await db.flush()
    return [run.id for run in runs]


async def list_runs(
    db: AsyncSession,
    course_id: int,
    profile_name: str | None = None,
    resource_id: int | None = None,
) -> list[dict]:
    query = (
        select(IngestionRun, IngestionProfile.name)
        .join(IngestionProfile, IngestionProfile.id == IngestionRun.profile_id)
        .where(IngestionRun.course_id == course_id)
        .order_by(IngestionRun.id.desc())
    )
    if profile_name is not None:
        query = query.where(IngestionProfile.name == profile_name)
    if resource_id is not None:
        query = query.where(IngestionRun.resource_id == resource_id)
    rows = (await db.execute(query)).all()
    return [serialize_run(run, name) for run, name in rows]


async def get_run(db: AsyncSession, course_id: int, run_id: int) -> dict:
    row = (
        await db.execute(
            select(IngestionRun, IngestionProfile.name)
            .join(IngestionProfile, IngestionProfile.id == IngestionRun.profile_id)
            .where(IngestionRun.id == run_id, IngestionRun.course_id == course_id)
        )
    ).first()
    if row is None:
        raise NotFoundError(f"Ingestion run {run_id} not found")
    return serialize_run(*row)
