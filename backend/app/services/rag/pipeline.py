"""
The query pipeline shared by /rag/compare and the auto-responder
(docs/design-rag.md §8.1): embed the question, retrieve the top chunks,
keep those at or above the threshold, and generate an answer from them.

answer() never touches the database. Its caller resolves the profile first
(rag_service.load_profile_spec) and passes a ProfileSpec, so nothing here
can write a Question or Post row (the T6 dry-run guarantee).
"""

from __future__ import annotations

import asyncio
import enum
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import psutil
import structlog

from ...common.exceptions import RagError
from ...config import settings
from . import prompting
from .clients import get_chroma, get_infinity, get_ollama

logger = structlog.get_logger()

# Chunks retrieved per question. Fixed, and not one of the T6 axes.
TOP_K = 4
SEED = 42

GTE_QUERY_INSTRUCTION = (
    "Instruct: Given a student's question about a course, retrieve course "
    "material passages that answer it\nQuery: "
)


class Priority(enum.Enum):
    COMPARE = "compare"
    AUTO = "auto"


@dataclass(frozen=True)
class ProfileSpec:
    course_id: int
    name: str
    collection_name: str
    embedding_model: str


@dataclass(frozen=True)
class Chunk:
    text: str
    metadata: dict
    similarity: float


@dataclass
class Result:
    matched: bool
    chunks: list[Chunk]
    prompt_chunks: list[Chunk]
    answer: str | None
    metrics: dict = field(default_factory=dict)
    truncated: bool = False


def normalize_model(name: str) -> str:
    """Ollama's own default: a name without a tag means `:latest`."""
    return name if ":" in name else f"{name}:latest"


def query_form(spec: ProfileSpec, question: str) -> str:
    # gte-Qwen2's model card requires an instruction on queries only.
    if "gte-qwen2" in spec.embedding_model.lower():
        return GTE_QUERY_INSTRUCTION + question
    return question


# ---------------------------------------------------------------------------
# One generation at a time, compare calls first (§8.1)
# ---------------------------------------------------------------------------


class _Slot:
    def __init__(self, priority: Priority):
        self.priority = priority
        self.preempted = asyncio.Event()


class GenerationLock:
    """
    Ollama runs one generation at a time, so the backend does too. A waiting
    compare call is served before any waiting auto-answer, and preempts an
    auto-answer that holds the lock. Auto-answers take the lock only when no
    compare call is waiting and none ended in the last COMPARE_GRACE_S.
    """

    def __init__(self) -> None:
        self._cond = asyncio.Condition()
        self._holder: _Slot | None = None
        self._compares: deque[_Slot] = deque()
        self._autos: deque[_Slot] = deque()
        self._last_compare_end = float("-inf")

    def _grace_left(self) -> float:
        since = time.monotonic() - self._last_compare_end
        return settings.COMPARE_GRACE_S - since

    def _can_take(self, slot: _Slot) -> bool:
        if self._holder is not None:
            return False
        if slot.priority is Priority.COMPARE:
            return self._compares[0] is slot
        return not self._compares and self._autos[0] is slot and self._grace_left() <= 0

    @asynccontextmanager
    async def hold(self, priority: Priority):
        slot = _Slot(priority)
        queue = self._compares if priority is Priority.COMPARE else self._autos
        async with self._cond:
            queue.append(slot)
            if (
                priority is Priority.COMPARE
                and self._holder is not None
                and self._holder.priority is Priority.AUTO
            ):
                self._holder.preempted.set()
            try:
                while not self._can_take(slot):
                    wait_s = None
                    if priority is Priority.AUTO and self._grace_left() > 0:
                        wait_s = self._grace_left()
                    try:
                        await asyncio.wait_for(self._cond.wait(), timeout=wait_s)
                    except TimeoutError:
                        pass
            except BaseException:
                queue.remove(slot)
                self._cond.notify_all()
                raise
            queue.popleft()
            self._holder = slot
        try:
            yield slot
        finally:
            async with self._cond:
                self._holder = None
                if priority is Priority.COMPARE:
                    self._last_compare_end = time.monotonic()
                self._cond.notify_all()


GENERATION_LOCK = GenerationLock()


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def _cpu_percent(before, after) -> float:
    """System-wide busy share between two psutil.cpu_times() snapshots (§8.1)."""
    total = sum(after) - sum(before)
    if total <= 0:
        return 0.0
    idle = (after.idle - before.idle) + (
        getattr(after, "iowait", 0) - getattr(before, "iowait", 0)
    )
    return max(0.0, min(100.0, 100.0 * (total - idle) / total))


def _ms(seconds: float) -> float:
    return round(seconds * 1000, 1)


# ---------------------------------------------------------------------------
# answer()
# ---------------------------------------------------------------------------


async def answer(
    spec: ProfileSpec,
    question: str,
    threshold: float,
    system_prompt: str,
    generation_model: str,
    *,
    priority: Priority,
    deadline: float | None = None,
) -> Result:
    """
    Raises RagError: 422 for a model that isn't pulled (never a fallback),
    409 for a profile whose collection is gone, 503 if a service is down,
    and 504 if an auto-answer attempt times out. A compare call (with a
    `deadline`) never gets a 504: it returns the partial answer instead.
    """
    ollama = get_ollama()
    model = normalize_model(generation_model)
    await ollama.require_model(model)
    cpu0 = psutil.cpu_times()

    t0 = time.monotonic()
    [qvec] = await get_infinity().embed(
        spec.embedding_model, [query_form(spec, question)]
    )
    t1 = time.monotonic()
    hits = await get_chroma().query_existing(
        spec.collection_name, qvec, TOP_K, where={"course_id": spec.course_id}
    )
    t2 = time.monotonic()

    ranked = [Chunk(h.document, h.metadata, h.similarity) for h in hits]
    kept = [c for c in ranked if c.similarity >= threshold]
    for c in ranked[len(kept) :]:
        logger.debug("rag_near_miss", similarity=round(c.similarity, 4))

    def metrics(generation_s: float) -> dict:
        return {
            "embedding_time_ms": _ms(t1 - t0),
            "retrieval_time_ms": _ms(t2 - t1),
            "generation_time_ms": _ms(generation_s),
            "cpu_percent": round(_cpu_percent(cpu0, psutil.cpu_times()), 1),
        }

    if not kept:
        return Result(False, [], [], None, metrics(0.0))

    prompt_chunks, user_msg = prompting.fit_prompt(system_prompt, kept, question)
    options = {
        "temperature": 0,
        "seed": SEED,
        "num_ctx": prompting.NUM_CTX,
        "num_predict": settings.OLLAMA_NUM_PREDICT,
    }
    while True:
        queued = time.monotonic()
        async with GENERATION_LOCK.hold(priority) as slot:
            t3 = time.monotonic()
            chat = await ollama.stream_chat(
                model,
                system_prompt,
                user_msg,
                options,
                deadline=deadline,
                timeout_s=None if deadline else settings.OLLAMA_TIMEOUT_S,
                preempt=slot.preempted if priority is Priority.AUTO else None,
            )
            t4 = time.monotonic()
        logger.info(
            "rag_generation",
            priority=priority.value,
            lock_wait_ms=_ms(t3 - queued),
            ended=chat.ended,
        )
        if chat.ended != "PREEMPTED":
            break

    if chat.prompt_eval_count and chat.prompt_eval_count >= (
        prompting.NUM_CTX - settings.OLLAMA_NUM_PREDICT
    ):
        logger.warning("rag_prompt_near_context_limit", tokens=chat.prompt_eval_count)
    if chat.ended == "TIMED_OUT":
        raise RagError("Generation timed out", 504, "GENERATION_TIMEOUT")
    text = chat.text
    truncated = chat.ended == "DEADLINE"
    if truncated:
        text += prompting.TRUNCATION_MARKER
    return Result(True, kept, prompt_chunks, text, metrics(t4 - t3), truncated)
