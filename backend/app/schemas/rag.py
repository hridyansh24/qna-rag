from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Citations on AI answers (docs/design-rag.md §4.1, §9.6)
# ---------------------------------------------------------------------------


class CitationResponse(BaseModel):
    rank: int
    resource_id: int | None
    resource_type: str
    label: str
    citation_url: str
    location: dict
    quoted_text: str
    similarity_score: float


# ---------------------------------------------------------------------------
# Ingestion profiles (§7.4)
# ---------------------------------------------------------------------------

MAX_TOKENS = 250  # chunking.MAX_TOKENS, repeated so schemas don't import tokenizers


class _Window(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_size: int = Field(ge=1, le=MAX_TOKENS)
    chunk_overlap: int = Field(ge=0, le=MAX_TOKENS)

    @model_validator(mode="after")
    def overlap_below_size(self):
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self


class SlidingWindowConfig(_Window):
    strategy: Literal["sliding_window"]


class OverflowConfig(_Window):
    pass


class SemanticConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: Literal["semantic"]
    breakpoint_percentile: int = Field(ge=5, le=95)
    max_tokens: int = Field(ge=1, le=MAX_TOKENS)
    overflow: OverflowConfig


ChunkerConfig = Annotated[
    SlidingWindowConfig | SemanticConfig, Field(discriminator="strategy")
]


class ChunkingConfig(BaseModel):
    """`default` applies to every type without its own key. Q&A is never chunked."""

    model_config = ConfigDict(extra="forbid")

    default: ChunkerConfig
    pdf: ChunkerConfig | None = None
    web: ChunkerConfig | None = None
    markdown: ChunkerConfig | None = None


PROFILE_NAME_PATTERN = r"^[a-z0-9][a-z0-9-]{0,38}[a-z0-9]$"


class ProfileCreate(BaseModel):
    name: str = Field(pattern=PROFILE_NAME_PATTERN)
    embedding_model: str
    chunking: ChunkingConfig


class ProfilePreset(BaseModel):
    name: str
    embedding_model: str
    chunking: dict


class ProfileResponse(BaseModel):
    name: str
    embedding_model: str
    chunking: dict
    collection_name: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Resources and runs (§9.5, §9.6)
# ---------------------------------------------------------------------------


class SkippedFile(BaseModel):
    path: str
    reason: str


class RunResponse(BaseModel):
    id: int
    resource_id: int
    profile: str
    status: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED"]
    chunk_count: int | None
    commit_sha: str | None
    error: str | None
    skipped_files: list[SkippedFile]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ResourceResponse(BaseModel):
    id: int
    resource_type: Literal["SYLLABUS", "SCHEDULE", "REPOSITORY", "QA_HISTORY"]
    source_kind: Literal["URL", "UPLOAD", "BOARD"]
    display_name: str
    url: str | None
    repo_ref: str | None
    upload_source_path: str | None
    files: list[str]
    last_commit_sha: str | None
    created_at: datetime
    latest_runs: dict[str, RunResponse | None]


class UploadResponse(ResourceResponse):
    skipped: list[SkippedFile]


class ResourceCreate(BaseModel):
    """Register a URL resource. Syntax only; addresses are checked at each fetch (§9.4)."""

    resource_type: Literal["SYLLABUS", "SCHEDULE", "REPOSITORY", "QA_HISTORY"]
    display_name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=2048)
    repo_ref: str | None = Field(default=None, max_length=255)


class SyncRequest(BaseModel):
    profile: str


class SyncStarted(BaseModel):
    run_id: int


class SyncAllStarted(BaseModel):
    run_ids: list[int]


# ---------------------------------------------------------------------------
# Live settings and the fixed T6 contract (§9.1, §9.5)
# ---------------------------------------------------------------------------


class RagSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    active_profile: str = Field(pattern=PROFILE_NAME_PATTERN)
    similarity_threshold: float = Field(ge=0.0, le=1.0)
    system_prompt: str = Field(min_length=1, max_length=10000)
    generation_model: str = Field(min_length=1, max_length=100)


class RagCompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=10000)
    ingestion_profile: str = Field(pattern=PROFILE_NAME_PATTERN)
    similarity_threshold: float = Field(ge=0.0, le=1.0)
    system_prompt: str = Field(min_length=1, max_length=10000)
    generation_model: str = Field(min_length=1, max_length=100)


class RetrievedChunk(BaseModel):
    resource_type: str
    source_url: str
    similarity_score: float
    text: str


class CompareMetrics(BaseModel):
    embedding_time_ms: float
    retrieval_time_ms: float
    generation_time_ms: float
    cpu_percent: float


class RagCompareResponse(BaseModel):
    matched: bool
    retrieved_chunks: list[RetrievedChunk]
    answer: str | None
    metrics: CompareMetrics
