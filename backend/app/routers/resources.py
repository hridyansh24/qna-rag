"""
Course resources, ingestion profiles and runs, and the uploaded-file
endpoint (docs/design-rag.md §9.5). Everything is staff-only except the file
endpoint, which every course member can read so citation links work.
"""

from __future__ import annotations

import asyncio
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..common.dependencies import (
    CourseMember,
    require_course_member,
    require_course_staff,
)
from ..common.uploads import read_upload_capped
from ..database import get_db
from ..schemas.rag import (
    ProfileCreate,
    ProfilePreset,
    ProfileResponse,
    ResourceCreate,
    ResourceResponse,
    RunResponse,
    SyncAllStarted,
    SyncRequest,
    SyncStarted,
    UploadResponse,
)
from ..services import resource_service
from ..services.rag import ingestion
from ..services.rag.sources import uploads, web

router = APIRouter(tags=["resources"])

Staff = Annotated[CourseMember, Depends(require_course_staff)]
Db = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@router.get("/courses/{course_id}/resources", response_model=list[ResourceResponse])
async def list_resources(course_id: int, member: Staff, db: Db):
    resources = await resource_service.list_resources(db, course_id, member.user)
    await db.commit()
    return resources


@router.post(
    "/courses/{course_id}/resources", response_model=ResourceResponse, status_code=201
)
async def register_resource(
    course_id: int, body: ResourceCreate, member: Staff, db: Db
):
    resource = await resource_service.register_url_resource(
        db, course_id, member.user, body
    )
    await db.commit()
    return await resource_service.serialize_resource(db, resource)


async def _upload_response(db: AsyncSession, resource, result) -> dict:
    return {
        **await resource_service.serialize_resource(db, resource),
        "skipped": result.skipped,
    }


@router.post(
    "/courses/{course_id}/resources/upload",
    response_model=UploadResponse,
    status_code=201,
)
async def upload_resource(
    course_id: int,
    member: Staff,
    db: Db,
    file: Annotated[UploadFile, File()],
    resource_type: Annotated[str, Form()],
    display_name: Annotated[str, Form()],
    source_path: Annotated[str, Form()],
):
    content = await read_upload_capped(file, max_bytes=uploads.MAX_UPLOAD_BYTES)
    resource, result = await resource_service.create_upload(
        db,
        course_id,
        member.user,
        resource_type,
        display_name,
        file.filename or "",
        content,
        source_path,
    )
    await db.commit()
    return await _upload_response(db, resource, result)


@router.put(
    "/courses/{course_id}/resources/{resource_id}/upload", response_model=UploadResponse
)
async def replace_resource_upload(
    course_id: int,
    resource_id: int,
    member: Staff,
    db: Db,
    file: Annotated[UploadFile, File()],
    source_path: Annotated[str, Form()],
):
    content = await read_upload_capped(file, max_bytes=uploads.MAX_UPLOAD_BYTES)
    resource, result = await resource_service.replace_upload(
        db, course_id, resource_id, file.filename or "", content, source_path
    )
    await db.commit()
    return await _upload_response(db, resource, result)


@router.delete("/courses/{course_id}/resources/{resource_id}", status_code=204)
async def delete_resource(course_id: int, resource_id: int, member: Staff, db: Db):
    await resource_service.delete_resource(db, course_id, resource_id)


@router.post(
    "/courses/{course_id}/resources/{resource_id}/sync",
    response_model=SyncStarted,
    status_code=202,
)
async def sync_resource(
    course_id: int,
    resource_id: int,
    body: SyncRequest,
    background: BackgroundTasks,
    member: Staff,
    db: Db,
):
    run_id = await resource_service.start_sync(db, course_id, resource_id, body.profile)
    await db.commit()
    background.add_task(ingestion.execute_run, run_id)
    return {"run_id": run_id}


@router.get("/courses/{course_id}/resources/{resource_id}/files/{path:path}")
async def get_resource_file(
    course_id: int,
    resource_id: int,
    path: str,
    member: Annotated[CourseMember, Depends(require_course_member)],
    db: Db,
    fmt: Annotated[str | None, Query(alias="format")] = None,
):
    """
    Uploaded files, for the source viewer (§5.5). Markdown and HTML are sent
    as plain text, never rendered on our origin; `?format=text` on an HTML
    file returns the document text that stored offsets index into.
    """
    target = await resource_service.stored_file(db, course_id, resource_id, path)
    headers = {"X-Content-Type-Options": "nosniff"}
    if fmt == "text" and PurePosixPath(path).suffix.lower() in uploads.WEB_EXTENSIONS:
        text = await asyncio.to_thread(lambda: web.document_text(target.read_bytes()))
        return PlainTextResponse(text, headers=headers)
    return FileResponse(
        target, media_type=uploads.media_type_for(target), headers=headers
    )


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


@router.get("/courses/{course_id}/profiles", response_model=list[ProfileResponse])
async def list_profiles(course_id: int, member: Staff, db: Db):
    return await resource_service.list_profiles(db, course_id)


@router.get("/courses/{course_id}/profiles/presets", response_model=list[ProfilePreset])
async def list_profile_presets(course_id: int, member: Staff):
    return resource_service.PRESETS


@router.post(
    "/courses/{course_id}/profiles", response_model=ProfileResponse, status_code=201
)
async def create_profile(course_id: int, body: ProfileCreate, member: Staff, db: Db):
    profile = await resource_service.create_profile(db, course_id, member.user, body)
    await db.commit()
    return resource_service.serialize_profile(profile)


@router.post(
    "/courses/{course_id}/profiles/{name}/sync-all",
    response_model=SyncAllStarted,
    status_code=202,
)
async def sync_all(
    course_id: int, name: str, background: BackgroundTasks, member: Staff, db: Db
):
    run_ids = await resource_service.start_sync_all(db, course_id, member.user, name)
    await db.commit()
    background.add_task(ingestion.execute_runs, run_ids)
    return {"run_ids": run_ids}


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


@router.get("/courses/{course_id}/ingestion-runs", response_model=list[RunResponse])
async def list_runs(
    course_id: int,
    member: Staff,
    db: Db,
    profile: str | None = None,
    resource_id: int | None = None,
):
    return await resource_service.list_runs(db, course_id, profile, resource_id)


@router.get("/courses/{course_id}/ingestion-runs/{run_id}", response_model=RunResponse)
async def get_run(course_id: int, run_id: int, member: Staff, db: Db):
    return await resource_service.get_run(db, course_id, run_id)
