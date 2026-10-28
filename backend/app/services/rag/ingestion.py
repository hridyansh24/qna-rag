"""
Ingestion runs: read the source, split, chunk, embed, upsert, then delete
the resource's stale chunks (docs/design-rag.md §7.5).

A run holds no database session while it reads files or calls Infinity and
Chroma (§3.4): one short session marks it RUNNING and snapshots what it
needs, another records the result. Old chunks are deleted only after every
new one is in, so a resource never disappears from retrieval mid-sync, and
the next successful sync repairs whatever a failed one left behind.
"""

from __future__ import annotations

import asyncio
import base64
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import PurePosixPath

import structlog
from sqlalchemy import select, update

from ...common.exceptions import QnaError
from ...config import settings
from ...database import AsyncSessionLocal
from ...models.qa import Question
from ...models.resource import CourseResource, IngestionProfile, IngestionRun
from . import citations
from .chunking import Embed, Span, chunk_id, chunk_with, qa_chunk_id
from .clients import EMBED_BATCH_SIZE, get_chroma, get_infinity
from .sources import fetch, markdown, pdf, qa_history, repo, uploads, web

logger = structlog.get_logger()

ACTIVE_STATUSES = ("QUEUED", "RUNNING")
WEB_RESOURCE_TYPES = {"SYLLABUS": "syllabus", "SCHEDULE": "schedule"}


class IngestionError(Exception):
    """A run failure whose message is safe to show staff."""


class SkipFile(Exception):
    """One file is skipped with this reason; the run goes on (§7.1)."""


def new_sync_id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Snapshots read in the run's first short session
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResourceSnapshot:
    id: int
    course_id: int
    resource_type: str
    source_kind: str
    display_name: str
    url: str | None
    upload_source_path: str | None
    repo_ref: str | None = None

    @classmethod
    def of(cls, r: CourseResource) -> ResourceSnapshot:
        return cls(
            r.id,
            r.course_id,
            r.resource_type,
            r.source_kind,
            r.display_name,
            r.url,
            r.upload_source_path,
            r.repo_ref,
        )


@dataclass(frozen=True)
class ProfileSnapshot:
    name: str
    embedding_model: str
    chunking: dict
    collection_name: str

    @classmethod
    def of(cls, p: IngestionProfile) -> ProfileSnapshot:
        return cls(p.name, p.embedding_model, p.chunking_json, p.collection_name)

    def chunker_for(self, kind: str) -> dict:
        """`kind` is "web", "markdown" or "pdf"; types without a key use `default`."""
        return self.chunking.get(kind) or self.chunking["default"]


@dataclass(frozen=True)
class ChunkRecord:
    id: str
    text: str
    metadata: dict


@dataclass
class Extracted:
    records: list[ChunkRecord] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    commit_sha: str | None = None


# ---------------------------------------------------------------------------
# Building chunk records (§4.2, §5)
# ---------------------------------------------------------------------------


def _metadata(
    res: ResourceSnapshot,
    profile: ProfileSnapshot,
    sync_id: str,
    resource_type: str,
    source_url: str,
    citation_url: str,
    label: str,
    **extra,
) -> dict:
    # Chroma takes flat scalars only and rejects None, so absent keys are left out.
    meta = {
        "course_id": res.course_id,
        "resource_id": res.id,
        "profile": profile.name,
        "sync_id": sync_id,
        "resource_type": resource_type,
        "source_url": source_url,
        "citation_url": citation_url,
        "label": label,
        "display_name": res.display_name,
    }
    meta.update({k: v for k, v in extra.items() if v is not None})
    return meta


def _rel_path(res: ResourceSnapshot, stored_path: str) -> str:
    """The path inside the resource: after a zip's base, or a single file's name."""
    base = res.upload_source_path or ""
    if base and not base.endswith("/"):
        return PurePosixPath(stored_path).name
    return stored_path[len(base) :]


@dataclass(frozen=True)
class Links:
    """
    Where one file's chunks link to (§5). `path` keys chunk IDs and is stored
    as `source_path`: an upload's stored path, a repository file's path, or
    the fetched page's URL. An upload links to the in-app viewer (§5.5); a
    URL resource to the live page (a Text Fragment, §5.1) or to GitLab,
    pinned to the cloned commit (§5.2, §5.3).
    """

    course_id: int
    resource_id: int
    path: str
    rel_path: str
    page_url: str | None = None  # a fetched syllabus or schedule
    repo_web: str | None = None  # a cloned repository's GitLab web URL
    commit_sha: str | None = None

    @classmethod
    def upload(cls, res: ResourceSnapshot, stored_path: str) -> Links:
        return cls(res.course_id, res.id, stored_path, _rel_path(res, stored_path))

    @classmethod
    def page(cls, res: ResourceSnapshot, url: str) -> Links:
        return cls(res.course_id, res.id, url, url, page_url=url)

    @classmethod
    def clone(cls, res: ResourceSnapshot, path: str, commit_sha: str) -> Links:
        web = citations.web_url(res.url or "")
        return cls(
            res.course_id, res.id, path, path, repo_web=web, commit_sha=commit_sha
        )

    def _upload_source(self) -> str:
        return citations.upload_source_url(self.course_id, self.resource_id, self.path)

    def web(
        self, start: int, end: int, text_start: str, text_end: str | None
    ) -> tuple[str, str]:
        """(citation_url, source_url) for a web-page chunk."""
        if self.page_url:
            return citations.fragment_url(
                self.page_url, text_start, text_end
            ), self.page_url
        query = f"chars={start}-{end}"
        return citations.viewer_url(
            self.resource_id, self.path, query
        ), self._upload_source()

    def markdown(self, a: int, b: int) -> tuple[str, str]:
        if self.repo_web:
            return citations.repo_markdown_urls(
                self.repo_web, self.commit_sha, self.path, a, b
            )
        return citations.viewer_url(
            self.resource_id, self.path, f"lines={a}-{b}"
        ), self._upload_source()

    def pdf(self, page: int) -> tuple[str, str]:
        if self.repo_web:
            return citations.repo_pdf_urls(
                self.repo_web, self.commit_sha, self.path, page
            )
        return citations.viewer_url(
            self.resource_id, self.path, f"page={page}"
        ), self._upload_source()


async def _web_records(
    res: ResourceSnapshot,
    profile: ProfileSnapshot,
    sync_id: str,
    links: Links,
    raw: bytes,
    embed: Embed,
) -> list[ChunkRecord]:
    doc = await asyncio.to_thread(web.clean_html, raw)
    blocks = [(b.start, b.end) for b in doc.blocks]
    resource_type = WEB_RESOURCE_TYPES[res.resource_type]
    records = []
    for section in web.split_sections(doc):
        for span in await chunk_with(
            profile.chunker_for("web"), doc.text, section, embed
        ):
            text_start, text_end = citations.text_fragment(
                doc.text, blocks, span.char_start, span.char_end, section.heading
            )
            citation_url, source_url = links.web(
                span.char_start, span.char_end, text_start, text_end
            )
            records.append(
                _span_record(
                    res,
                    links.path,
                    span,
                    doc.text,
                    _metadata(
                        res,
                        profile,
                        sync_id,
                        resource_type,
                        source_url,
                        citation_url,
                        citations.web_label(res.display_name, section.path),
                        source_path=links.path,
                        section=section.path,
                        text_start=text_start,
                        text_end=text_end,
                    ),
                )
            )
    return records


async def _markdown_records(
    res: ResourceSnapshot,
    profile: ProfileSnapshot,
    sync_id: str,
    links: Links,
    raw: bytes,
    embed: Embed,
) -> list[ChunkRecord]:
    try:
        text = markdown.markdown_text(raw)
    except UnicodeDecodeError:
        raise SkipFile("not valid UTF-8")
    rel_path = links.rel_path
    lines = citations.LineIndex(text)
    records = []
    for section in markdown.split_markdown(text, PurePosixPath(rel_path).name):
        for span in await chunk_with(
            profile.chunker_for("markdown"), text, section, embed
        ):
            a, b = lines.lines(span.char_start, span.char_end)
            citation_url, source_url = links.markdown(a, b)
            records.append(
                _span_record(
                    res,
                    links.path,
                    span,
                    text,
                    _metadata(
                        res,
                        profile,
                        sync_id,
                        "repo_markdown",
                        source_url,
                        citation_url,
                        citations.markdown_label(res.display_name, rel_path, a, b),
                        source_path=links.path,
                        rel_path=rel_path,
                        section=section.path,
                        line_start=a,
                        line_end=b,
                    ),
                )
            )
    return records


async def _pdf_records(
    res: ResourceSnapshot,
    profile: ProfileSnapshot,
    sync_id: str,
    links: Links,
    raw: bytes,
    embed: Embed,
) -> list[ChunkRecord]:
    try:
        doc = await asyncio.to_thread(pdf.pdf_document, raw)
    except pdf.UnreadablePdf as exc:
        raise SkipFile(str(exc))
    rel_path = links.rel_path
    pages = citations.PageIndex(doc.page_starts)
    records = []
    for section in pdf.split_pages(doc):
        for span in await chunk_with(
            profile.chunker_for("pdf"), doc.text, section, embed
        ):
            page = pages.page_of(span.char_start)
            citation_url, source_url = links.pdf(page)
            records.append(
                _span_record(
                    res,
                    links.path,
                    span,
                    doc.text,
                    _metadata(
                        res,
                        profile,
                        sync_id,
                        "repo_pdf",
                        source_url,
                        citation_url,
                        citations.pdf_label(res.display_name, rel_path, page),
                        source_path=links.path,
                        rel_path=rel_path,
                        page=page,
                    ),
                )
            )
    return records


def _span_record(
    res: ResourceSnapshot, stored_path: str, span: Span, doc_text: str, meta: dict
) -> ChunkRecord:
    meta["char_start"], meta["char_end"] = span.char_start, span.char_end
    return ChunkRecord(
        chunk_id(res.id, stored_path, span),
        doc_text[span.char_start : span.char_end],
        meta,
    )


def qa_record(
    course_id: int,
    resource_id: int,
    display_name: str,
    profile_name: str,
    sync_id: str,
    thread: qa_history.QaThread,
) -> ChunkRecord:
    """One chunk per thread, never split (§5.4)."""
    url = citations.qa_url(thread.question_id)
    return ChunkRecord(
        qa_chunk_id(thread.question_id),
        thread.document(),
        {
            "course_id": course_id,
            "resource_id": resource_id,
            "profile": profile_name,
            "sync_id": sync_id,
            "resource_type": "qa_thread",
            "source_url": url,
            "citation_url": url,
            "label": citations.qa_label(thread.title),
            "display_name": display_name,
            "question_id": thread.question_id,
        },
    )


async def _file_records(
    res: ResourceSnapshot,
    profile: ProfileSnapshot,
    sync_id: str,
    links: Links,
    raw: bytes,
    embed: Embed,
) -> list[ChunkRecord]:
    ext = PurePosixPath(links.path).suffix.lower()
    if res.resource_type in WEB_RESOURCE_TYPES and ext in uploads.WEB_EXTENSIONS:
        build = _web_records
    elif res.resource_type == "REPOSITORY" and ext == ".md":
        build = _markdown_records
    elif res.resource_type == "REPOSITORY" and ext == ".pdf":
        build = _pdf_records
    else:
        raise SkipFile("unsupported type")
    records = await build(res, profile, sync_id, links, raw, embed)
    if not records:
        raise SkipFile("no extractable text")
    return records


async def _files_records(
    res: ResourceSnapshot,
    profile: ProfileSnapshot,
    sync_id: str,
    files: list[tuple[Links, bytes]],
    embed: Embed,
    out: Extracted,
) -> Extracted:
    """Every file's records into `out`; one bad file is skipped, not fatal (§7.1)."""
    for links, raw in files:
        try:
            out.records.extend(
                await _file_records(res, profile, sync_id, links, raw, embed)
            )
        except SkipFile as exc:
            out.skipped.append({"path": links.path, "reason": str(exc)})
    if not out.records:
        raise IngestionError("no readable files")
    return out


async def _url_extract(
    res: ResourceSnapshot, profile: ProfileSnapshot, sync_id: str, embed: Embed
) -> Extracted:
    """A URL resource is fetched or cloned again on every sync (§7.1)."""
    if res.resource_type in WEB_RESOURCE_TYPES:
        try:
            page = await fetch.fetch_page(res.url or "")
        except fetch.FetchError as exc:
            raise IngestionError(f"Couldn't fetch the page: {exc}")
        records = await _web_records(
            res, profile, sync_id, Links.page(res, page.url), page.content, embed
        )
        if not records:
            raise IngestionError("The page has no extractable text")
        return Extracted(records)
    try:
        cloned = await repo.clone_files(res.url or "", res.repo_ref)
    except repo.CloneError as exc:
        raise IngestionError(f"Couldn't clone the repository: {exc}")
    files = [
        (Links.clone(res, path, cloned.commit_sha), raw) for path, raw in cloned.files
    ]
    out = Extracted(skipped=list(cloned.skipped), commit_sha=cloned.commit_sha)
    if not files:
        raise IngestionError("The repository has no .md or .pdf files")
    return await _files_records(res, profile, sync_id, files, embed, out)


async def extract(
    res: ResourceSnapshot, profile: ProfileSnapshot, sync_id: str, embed: Embed
) -> Extracted:
    """Every chunk record for one resource under one profile."""
    if res.source_kind == "BOARD":
        async with AsyncSessionLocal() as db:
            threads = await qa_history.load_threads(db, res.course_id)
        return Extracted(
            [
                qa_record(
                    res.course_id, res.id, res.display_name, profile.name, sync_id, t
                )
                for t in threads
            ]
        )
    if res.source_kind == "URL":
        return await _url_extract(res, profile, sync_id, embed)

    files = await asyncio.to_thread(
        lambda: [
            (p, path.read_bytes()) for p, path in uploads.iter_stored_files(res.id)
        ]
    )
    if not files:
        raise IngestionError("No uploaded files are stored for this resource")
    stored = [(Links.upload(res, p), raw) for p, raw in files]
    return await _files_records(res, profile, sync_id, stored, embed, Extracted())


# ---------------------------------------------------------------------------
# Writing to Chroma
# ---------------------------------------------------------------------------


def embedder(model: str) -> Embed:
    async def embed(texts: list[str]) -> list[list[float]]:
        return await get_infinity().embed(
            model, texts, timeout_s=settings.INFINITY_BATCH_TIMEOUT_S
        )

    return embed


async def upsert_records(profile: ProfileSnapshot, records: list[ChunkRecord]) -> int:
    """Embed and upsert in the model's batch size. Returns how many were written."""
    chroma = get_chroma()
    await chroma.get_or_create(profile.collection_name)
    unique = list({r.id: r for r in reversed(records)}.values())[::-1]
    size = settings.rag_embed_batch_sizes.get(profile.embedding_model, EMBED_BATCH_SIZE)
    embed = embedder(profile.embedding_model)
    for start in range(0, len(unique), size):
        batch = unique[start : start + size]
        vectors = await embed([r.text for r in batch])
        await chroma.upsert(
            profile.collection_name,
            ids=[r.id for r in batch],
            embeddings=vectors,
            documents=[r.text for r in batch],
            metadatas=[r.metadata for r in batch],
        )
    return len(unique)


async def delete_stale(
    profile: ProfileSnapshot, resource_id: int, sync_id: str
) -> None:
    # Chroma requires $and when a where filter has more than one condition.
    await get_chroma().delete(
        profile.collection_name,
        where={"$and": [{"resource_id": resource_id}, {"sync_id": {"$ne": sync_id}}]},
    )


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def scrub(message: str) -> str:
    """Remove the GitLab token, and the Basic header value built from it (§9.4)."""
    token = settings.GITLAB_TOKEN
    if token:
        header = base64.b64encode(f"oauth2:{token}".encode()).decode()
        for secret in (header, token):
            message = message.replace(secret, "***")
    return message


def _error_message(exc: Exception) -> str:
    if isinstance(exc, (IngestionError, SkipFile)):
        message = str(exc)
    elif isinstance(exc, QnaError):
        message = exc.message
    else:
        message = f"{type(exc).__name__}: {exc}"
    return scrub(message)[:1000]


async def _begin(run_id: int) -> tuple[str, ResourceSnapshot, ProfileSnapshot] | None:
    async with AsyncSessionLocal() as db:
        run = await db.get(IngestionRun, run_id, with_for_update=True)
        if run is None or run.status not in ACTIVE_STATUSES:
            return None
        resource = await db.get(CourseResource, run.resource_id)
        profile = await db.get(IngestionProfile, run.profile_id)
        if run.status == "QUEUED":
            run.status = "RUNNING"
            run.started_at = _now()
        snapshot = (
            run.sync_id,
            ResourceSnapshot.of(resource),
            ProfileSnapshot.of(profile),
        )
        await db.commit()
    return snapshot


async def _finish(run_id: int, status: str, **values) -> None:
    async with AsyncSessionLocal() as db:
        run = await db.get(IngestionRun, run_id)
        if run is None:
            return
        run.status = status
        run.finished_at = _now()
        for key, value in values.items():
            setattr(run, key, value)
        if status == "SUCCEEDED" and values.get("commit_sha"):
            resource = await db.get(CourseResource, run.resource_id)
            resource.last_commit_sha = values["commit_sha"]
        await db.commit()


async def execute_run(run_id: int) -> None:
    """One run, start to finish. Never raises: failures are recorded on the run."""
    try:
        begun = await _begin(run_id)
    except Exception:  # a background task must not die silently
        logger.exception("ingestion_start_failed", run_id=run_id)
        return
    if begun is None:
        return
    sync_id, res, profile = begun
    log = logger.bind(run_id=run_id, resource_id=res.id, profile=profile.name)
    upserting = False
    try:
        extracted = await extract(
            res, profile, sync_id, embedder(profile.embedding_model)
        )
        upserting = True
        count = await upsert_records(profile, extracted.records)
        await delete_stale(profile, res.id, sync_id)
    except Exception as exc:  # recorded on the run for staff
        error = _error_message(exc)
        if upserting:
            error += (
                " Some chunks may already have been replaced; sync again to clean up."
            )
        log.warning(
            "ingestion_failed",
            error=error,
            exc_info=not isinstance(exc, QnaError | IngestionError),
        )
        await _record_failure(run_id, error)
        return
    try:
        await _finish(
            run_id,
            "SUCCEEDED",
            chunk_count=count,
            skipped_json=extracted.skipped,
            commit_sha=extracted.commit_sha,
        )
    except Exception:
        log.exception("ingestion_finish_failed")
        return
    log.info("ingestion_succeeded", chunks=count, skipped=len(extracted.skipped))


async def _record_failure(run_id: int, error: str) -> None:
    try:
        await _finish(run_id, "FAILED", error=error)
    except Exception:
        logger.exception("ingestion_finish_failed", run_id=run_id)


async def execute_runs(run_ids: list[int]) -> None:
    """A sync-all: one run after another; a failed run doesn't stop the rest (§7.5)."""
    for run_id in run_ids:
        await execute_run(run_id)


async def fail_interrupted_work() -> None:
    """
    On startup, nothing can still be running: mark leftover runs and
    pending auto-answers FAILED (§4.1, §6.3).
    """
    async with AsyncSessionLocal() as db:
        runs = await db.execute(
            update(IngestionRun)
            .where(IngestionRun.status.in_(ACTIVE_STATUSES))
            .values(status="FAILED", error="interrupted by restart", finished_at=_now())
        )
        questions = await db.execute(
            update(Question)
            .where(Question.ai_status == "PENDING")
            # Keep updated_at: a status change isn't thread activity.
            .values(ai_status="FAILED", updated_at=Question.updated_at)
        )
        await db.commit()
    if runs.rowcount or questions.rowcount:
        logger.warning(
            "interrupted_work_failed", runs=runs.rowcount, questions=questions.rowcount
        )


async def latest_qa_targets(
    db, course_id: int
) -> tuple[CourseResource | None, list[tuple[ProfileSnapshot, str]]]:
    """
    The QA_HISTORY resource, and for each profile with a SUCCEEDED Q&A run
    the sync_id an event's chunk should carry: the RUNNING run's if there is
    one, else the latest SUCCEEDED run's (§7.6).
    """
    qa = await db.scalar(
        select(CourseResource).where(
            CourseResource.course_id == course_id,
            CourseResource.resource_type == "QA_HISTORY",
        )
    )
    if qa is None:
        return None, []
    targets = []
    profiles = await db.scalars(
        select(IngestionProfile).where(IngestionProfile.course_id == course_id)
    )
    for profile in profiles:
        rows = (
            await db.execute(
                select(IngestionRun.status, IngestionRun.sync_id)
                .where(
                    IngestionRun.resource_id == qa.id,
                    IngestionRun.profile_id == profile.id,
                    IngestionRun.status.in_(("RUNNING", "SUCCEEDED")),
                )
                .order_by(IngestionRun.id.desc())
            )
        ).all()
        succeeded = [s for status, s in rows if status == "SUCCEEDED"]
        if not succeeded:
            continue
        running = [s for status, s in rows if status == "RUNNING"]
        targets.append((ProfileSnapshot.of(profile), (running or succeeded)[0]))
    return qa, targets
