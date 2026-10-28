"""
Unit tests for the RAG service clients (backend/app/services/rag/clients.py).

The services themselves are faked with httpx.MockTransport, so these run
without Docker. What matters here is the contract the pipeline relies on:
embeddings come back in input order across batches, an unpulled model is a
422 (T6: never fall back), and every connection failure or service error is a
503 RagServiceUnavailableError rather than an unhandled 500.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.common.exceptions import RagError, RagServiceUnavailableError
from app.services.rag import clients
from app.services.rag.clients import ChromaHit, InfinityClient, OllamaClient


def _infinity(handler) -> InfinityClient:
    return InfinityClient("http://infinity:7997", transport=httpx.MockTransport(handler))


def _ollama(handler) -> OllamaClient:
    return OllamaClient("http://ollama:11434", transport=httpx.MockTransport(handler))


async def test_embed_preserves_order_across_batches(monkeypatch):
    monkeypatch.setattr(clients, "EMBED_BATCH_SIZE", 2)
    seen_batches = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen_batches.append(body["input"])
        assert body["model"] == "m"
        # Return the items out of order: the client must sort by "index".
        data = [
            {"index": i, "embedding": [float(len(text))]}
            for i, text in enumerate(body["input"])
        ]
        return httpx.Response(200, json={"data": list(reversed(data))})

    vectors = await _infinity(handler).embed("m", ["a", "bb", "ccc", "dddd", "eeeee"])

    assert seen_batches == [["a", "bb"], ["ccc", "dddd"], ["eeeee"]]
    assert vectors == [[1.0], [2.0], [3.0], [4.0], [5.0]]


async def test_embed_rejects_a_short_response():
    def handler(request):
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1]}]})

    with pytest.raises(RagServiceUnavailableError):
        await _infinity(handler).embed("m", ["one", "two"])


async def test_infinity_unreachable_is_503():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(RagServiceUnavailableError) as exc:
        await _infinity(handler).embed("m", ["x"])
    assert exc.value.status_code == 503


async def test_infinity_error_status_is_503():
    def handler(request):
        return httpx.Response(400, json={"detail": "model not loaded"})

    with pytest.raises(RagServiceUnavailableError):
        await _infinity(handler).embed("unknown-model", ["x"])


async def test_list_models_reads_name_and_model_fields():
    def handler(request):
        assert request.url.path == "/api/tags"
        return httpx.Response(
            200,
            json={"models": [{"name": "qwen2.5:1.5b", "model": "qwen2.5:1.5b"},
                             {"name": "llama3.2:1b"}]},
        )

    assert await _ollama(handler).list_models() == {"qwen2.5:1.5b", "llama3.2:1b"}


async def test_require_model_rejects_an_unpulled_model_with_422():
    def handler(request):
        return httpx.Response(200, json={"models": [{"name": "qwen2.5:1.5b"}]})

    with pytest.raises(RagError) as exc:
        await _ollama(handler).require_model("qwen2.5:3b")
    assert exc.value.status_code == 422


async def test_chat_sends_system_user_and_options_without_streaming():
    captured = {}

    def handler(request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "3"}})

    answer = await _ollama(handler).chat(
        "qwen2.5:1.5b", "be grounded", "how many?", {"temperature": 0, "seed": 42}
    )

    assert answer == "3"
    assert captured["stream"] is False
    assert captured["options"] == {"temperature": 0, "seed": 42}
    assert captured["messages"] == [
        {"role": "system", "content": "be grounded"},
        {"role": "user", "content": "how many?"},
    ]


async def test_chat_404_means_model_not_pulled():
    def handler(request):
        return httpx.Response(404, json={"error": "model 'x' not found"})

    with pytest.raises(RagError) as exc:
        await _ollama(handler).chat("x", "s", "u")
    assert exc.value.status_code == 422


async def test_ollama_unreachable_is_503():
    def handler(request):
        raise httpx.ReadTimeout("timed out")

    with pytest.raises(RagServiceUnavailableError):
        await _ollama(handler).list_models()


def test_chroma_hit_similarity_is_one_minus_cosine_distance():
    hit = ChromaHit(id="a", document="", metadata={}, distance=0.25)
    assert hit.similarity == pytest.approx(0.75)


def test_get_chroma_parses_host_and_port(monkeypatch):
    monkeypatch.setattr(clients, "_chroma", None)
    monkeypatch.setattr(clients.settings, "CHROMA_URL", "http://chromadb:8123")
    store = clients.get_chroma()
    assert (store._host, store._port) == ("chromadb", 8123)
    monkeypatch.setattr(clients, "_chroma", None)
