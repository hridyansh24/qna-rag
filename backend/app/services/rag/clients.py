"""
Thin async clients for the three RAG services (docs/design-rag.md §3, §9.2).

- InfinityClient: embeddings, via Infinity's OpenAI-compatible POST /embeddings.
- OllamaClient: generation, via POST /api/chat, plus GET /api/tags to check a
  model is pulled before using it (the endpoint never pulls, and never falls
  back to another model).
- ChromaStore: the vector store, one collection per (course, profile), always
  created with cosine distance.

Every connection failure or unexpected service error becomes a
RagServiceUnavailableError (503), so routers return the error shape the
design specifies instead of an unhandled 500. These clients hold no database
session and know nothing about courses or profiles beyond the names they're
given; that keeps pipeline.answer() free of DB access (§3.3).
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Literal

import chromadb
import httpx
import structlog
from chromadb.config import Settings as ChromaSettings

from ...common.exceptions import RagError, RagServiceUnavailableError
from ...config import settings

logger = structlog.get_logger()

# Texts per Infinity request for a model not in RAG_EMBED_BATCH_SIZES.
# gte-Qwen2 on CPU is listed with 4, so one slow request stays well under
# the batch timeout (§7.5).
EMBED_BATCH_SIZE = 32

# compare_harness.py gives each /rag/compare call 180s; generation must
# finish inside that with room for embedding and retrieval.
OLLAMA_CHAT_TIMEOUT_S = 170.0


class InfinityClient:
    def __init__(
        self, base_url: str, transport: httpx.AsyncBaseTransport | None = None
    ):
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(settings.INFINITY_QUERY_TIMEOUT_S, connect=5.0),
            transport=transport,
        )

    async def models(self) -> list[str]:
        data = await self._request("GET", "/models")
        return [m["id"] for m in data.get("data", [])]

    async def embed(
        self, model: str, texts: list[str], *, timeout_s: float | None = None
    ) -> list[list[float]]:
        """
        Embed `texts` with `model`, preserving input order, in that model's
        batch size. Queries use the client's 30 s default; ingestion passes
        INFINITY_BATCH_TIMEOUT_S.
        """
        size = settings.rag_embed_batch_sizes.get(model, EMBED_BATCH_SIZE)
        extra = (
            {}
            if timeout_s is None
            else {"timeout": httpx.Timeout(timeout_s, connect=5.0)}
        )
        vectors: list[list[float]] = []
        for start in range(0, len(texts), size):
            batch = texts[start : start + size]
            data = await self._request(
                "POST", "/embeddings", json={"model": model, "input": batch}, **extra
            )
            items = sorted(data["data"], key=lambda item: item["index"])
            if len(items) != len(batch):
                raise RagServiceUnavailableError(
                    f"Infinity returned {len(items)} embeddings for {len(batch)} inputs"
                )
            vectors.extend(item["embedding"] for item in items)
        return vectors

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        try:
            resp = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            logger.error("infinity_unreachable", error=str(exc))
            raise RagServiceUnavailableError(
                "Embedding service (Infinity) is unreachable"
            )
        if resp.status_code != 200:
            logger.error(
                "infinity_error", status=resp.status_code, body=resp.text[:500]
            )
            raise RagServiceUnavailableError(
                f"Embedding service (Infinity) returned HTTP {resp.status_code}"
            )
        return resp.json()

    async def aclose(self) -> None:
        await self._client.aclose()


class OllamaClient:
    def __init__(
        self, base_url: str, transport: httpx.AsyncBaseTransport | None = None
    ):
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(OLLAMA_CHAT_TIMEOUT_S, connect=5.0),
            transport=transport,
        )

    async def list_models(self) -> set[str]:
        """Names of every pulled model, e.g. {"qwen2.5:1.5b"}."""
        data = await self._request("GET", "/api/tags")
        names: set[str] = set()
        for m in data.get("models", []):
            names.update(n for n in (m.get("name"), m.get("model")) if n)
        return names

    async def require_model(self, model: str) -> None:
        """422 unless `model` is already pulled (T6: never pull, never fall back)."""
        if model not in await self.list_models():
            raise RagError(
                f"Model '{model}' is not pulled in Ollama", 422, "MODEL_NOT_AVAILABLE"
            )

    async def chat(
        self, model: str, system: str, user: str, options: dict[str, Any] | None = None
    ) -> str:
        data = await self._request(
            "POST",
            "/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "options": options or {},
            },
        )
        return data["message"]["content"]

    async def stream_chat(
        self,
        model: str,
        system: str,
        user: str,
        options: dict[str, Any],
        *,
        deadline: float | None = None,
        timeout_s: float | None = None,
        preempt: asyncio.Event | None = None,
    ) -> ChatResult:
        """
        Stream one chat completion (§8.1). It stops early, keeping whatever
        tokens arrived, when `deadline` (a time.monotonic() value) passes,
        when `timeout_s` runs out, or when `preempt` is set. Stopping cancels
        the read, which closes the connection, and Ollama then abandons the
        request.
        """
        parts: list[str] = []
        stats: dict[str, Any] = {}

        async def consume() -> None:
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": True,
                "options": options,
            }
            try:
                async with self._client.stream("POST", "/api/chat", json=body) as resp:
                    if resp.status_code == 404:
                        raise RagError(
                            f"Model '{model}' is not pulled in Ollama",
                            422,
                            "MODEL_NOT_AVAILABLE",
                        )
                    if resp.status_code != 200:
                        text = (await resp.aread()).decode(errors="replace")
                        logger.error(
                            "ollama_error", status=resp.status_code, body=text[:500]
                        )
                        raise RagServiceUnavailableError(
                            f"Generation service (Ollama) returned HTTP {resp.status_code}"
                        )
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        event = json.loads(line)
                        if event.get("error"):
                            raise RagServiceUnavailableError(
                                f"Generation service (Ollama) error: {event['error']}"
                            )
                        parts.append(event.get("message", {}).get("content", ""))
                        if event.get("done"):
                            stats.update(event)
                            return
            except httpx.HTTPError as exc:
                logger.error("ollama_unreachable", error=str(exc))
                raise RagServiceUnavailableError(
                    "Generation service (Ollama) is unreachable"
                )

        limits = []
        if deadline is not None:
            limits.append(("DEADLINE", deadline - time.monotonic()))
        if timeout_s is not None:
            limits.append(("TIMED_OUT", timeout_s))
        reason, wait_s = min(limits, key=lambda x: x[1]) if limits else (None, None)

        reader = asyncio.create_task(consume())
        waiters: set[asyncio.Task] = {reader}
        preempted = None
        if preempt is not None:
            preempted = asyncio.create_task(preempt.wait())
            waiters.add(preempted)
        try:
            done, _ = await asyncio.wait(
                waiters,
                timeout=None if wait_s is None else max(wait_s, 0),
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            if preempted is not None:
                preempted.cancel()
            if not reader.done():
                reader.cancel()
                try:
                    await reader
                except (asyncio.CancelledError, Exception):
                    pass

        text = "".join(parts)
        if reader in done:
            reader.result()  # re-raises a RagError from the stream
            return ChatResult(text, "DONE", stats.get("prompt_eval_count"))
        if preempted is not None and preempted in done:
            return ChatResult(text, "PREEMPTED", None)
        return ChatResult(text, reason, None)

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        try:
            resp = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            logger.error("ollama_unreachable", error=str(exc))
            raise RagServiceUnavailableError(
                "Generation service (Ollama) is unreachable"
            )
        if resp.status_code == 404 and path == "/api/chat":
            # Ollama answers 404 for a model that isn't pulled.
            raise RagError(
                f"Model '{kwargs['json']['model']}' is not pulled in Ollama",
                422,
                "MODEL_NOT_AVAILABLE",
            )
        if resp.status_code != 200:
            logger.error("ollama_error", status=resp.status_code, body=resp.text[:500])
            raise RagServiceUnavailableError(
                f"Generation service (Ollama) returned HTTP {resp.status_code}"
            )
        return resp.json()

    async def aclose(self) -> None:
        await self._client.aclose()


@dataclass(frozen=True)
class ChatResult:
    text: str
    # DONE: the model finished. DEADLINE: compare's budget ran out.
    # TIMED_OUT: an auto-answer attempt ran out. PREEMPTED: a compare call
    # took the model.
    ended: Literal["DONE", "DEADLINE", "TIMED_OUT", "PREEMPTED"]
    prompt_eval_count: int | None


@dataclass(frozen=True)
class ChromaHit:
    id: str
    document: str
    metadata: dict[str, Any]
    distance: float

    @property
    def similarity(self) -> float:
        # Collections use cosine distance, so similarity = 1 - distance (§8.1).
        return 1.0 - self.distance


class ChromaStore:
    """
    Wraps chromadb.AsyncHttpClient. Collections are created with cosine
    distance and no embedding function: every vector comes from Infinity, so
    Chroma must never try to embed text itself (its default ONNX function
    isn't installed in the thin client).
    """

    def __init__(self, host: str, port: int):
        self._host = host
        self._port = port
        self._client: chromadb.api.AsyncClientAPI | None = None

    async def _api(self) -> chromadb.api.AsyncClientAPI:
        if self._client is None:
            try:
                self._client = await chromadb.AsyncHttpClient(
                    host=self._host,
                    port=self._port,
                    settings=ChromaSettings(anonymized_telemetry=False),
                )
            except Exception as exc:
                logger.error("chroma_unreachable", error=str(exc))
                raise RagServiceUnavailableError(
                    "Vector store (ChromaDB) is unreachable"
                )
        return self._client

    async def heartbeat(self) -> int:
        return await self._call(lambda api: api.heartbeat())

    async def get_or_create(self, name: str):
        return await self._call(
            lambda api: api.get_or_create_collection(
                name=name,
                configuration={"hnsw": {"space": "cosine"}},
                embedding_function=None,
            )
        )

    async def upsert(
        self,
        name: str,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        collection = await self.get_or_create(name)
        await self._call(
            lambda _: collection.upsert(
                ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas
            )
        )

    async def query(
        self, name: str, embedding: list[float], n_results: int, where: dict[str, Any]
    ) -> list[ChromaHit]:
        """Nearest chunks, best first. A collection that doesn't exist yet has no hits."""
        collection = await self.get_or_create(name)
        result = await self._call(
            lambda _: collection.query(
                query_embeddings=[embedding],
                n_results=n_results,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        )
        return [
            ChromaHit(
                id=i, document=doc or "", metadata=dict(meta or {}), distance=dist
            )
            for i, doc, meta, dist in zip(
                result["ids"][0],
                result["documents"][0],
                result["metadatas"][0],
                result["distances"][0],
            )
        ]

    async def query_existing(
        self, name: str, embedding: list[float], n_results: int, where: dict[str, Any]
    ) -> list[ChromaHit]:
        """
        Like query(), but a missing collection is a 409 instead of being
        created: the profile's run rows say it was ingested, so the volume
        was lost and the profile needs a re-sync (§8.1).
        """
        try:
            collection = await self._call(lambda api: api.get_collection(name=name))
        except RagServiceUnavailableError as exc:
            if "does not exist" in exc.message or "NotFound" in exc.message:
                raise RagError(
                    "Profile has no ingested content; re-sync it",
                    409,
                    "PROFILE_NOT_INGESTED",
                )
            raise
        result = await self._call(
            lambda _: collection.query(
                query_embeddings=[embedding],
                n_results=n_results,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        )
        return [
            ChromaHit(
                id=i, document=doc or "", metadata=dict(meta or {}), distance=dist
            )
            for i, doc, meta, dist in zip(
                result["ids"][0],
                result["documents"][0],
                result["metadatas"][0],
                result["distances"][0],
            )
        ]

    async def delete(
        self,
        name: str,
        *,
        ids: list[str] | None = None,
        where: dict[str, Any] | None = None,
    ) -> None:
        collection = await self.get_or_create(name)
        await self._call(lambda _: collection.delete(ids=ids, where=where))

    async def count(self, name: str) -> int:
        collection = await self.get_or_create(name)
        return await self._call(lambda _: collection.count())

    async def delete_collection(self, name: str) -> None:
        await self._call(lambda api: api.delete_collection(name=name))

    async def _call(self, fn):
        api = await self._api()
        try:
            return await fn(api)
        except RagError:
            raise
        except Exception as exc:
            logger.error("chroma_error", error=str(exc))
            raise RagServiceUnavailableError(f"Vector store (ChromaDB) error: {exc}")


# ---------------------------------------------------------------------------
# Process-wide singletons, built from settings on first use
# ---------------------------------------------------------------------------

_infinity: InfinityClient | None = None
_ollama: OllamaClient | None = None
_chroma: ChromaStore | None = None


def get_infinity() -> InfinityClient:
    global _infinity
    if _infinity is None:
        _infinity = InfinityClient(settings.INFINITY_URL)
    return _infinity


def get_ollama() -> OllamaClient:
    global _ollama
    if _ollama is None:
        _ollama = OllamaClient(settings.OLLAMA_URL)
    return _ollama


def get_chroma() -> ChromaStore:
    global _chroma
    if _chroma is None:
        url = httpx.URL(settings.CHROMA_URL)
        _chroma = ChromaStore(url.host, url.port or 8000)
    return _chroma


async def close_clients() -> None:
    global _infinity, _ollama, _chroma
    if _infinity is not None:
        await _infinity.aclose()
    if _ollama is not None:
        await _ollama.aclose()
    _infinity = _ollama = _chroma = None
