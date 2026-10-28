"""
End-to-end smoke test for the three RAG services (docs/design-rag.md §15 step 2).

Run it inside the backend container once the stack is up and the default
model is pulled (scripts/pull_models.sh):

    docker compose exec backend python scripts/rag_smoke.py

It exercises exactly the client calls the pipeline and ingestion use, and
checks the §12 claims that can only be verified against running services:

  1. Infinity serves every model in INFINITY_MODEL_ID and embeds in order.
  2. A Chroma collection created with cosine space returns distances where
     1 - distance equals the cosine similarity computed locally.
  3. Chroma's delete(where={"$and": [..., {"sync_id": {"$ne": ...}}]}) removes
     only the stale rows (the sync algorithm, §7.5).
  4. Ollama's /api/tags lists the default model, an unpulled model is
     rejected, and /api/chat with temperature 0 and a fixed seed gives the
     same answer twice (reproducibility, §8.1).

It creates and then deletes one throwaway collection, `qna_smoke_test`.
Exit status is 0 only if every check passes.
"""

from __future__ import annotations

import asyncio
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.common.exceptions import RagError  # noqa: E402
from app.config import settings  # noqa: E402
from app.services.rag.clients import (  # noqa: E402
    close_clients,
    get_chroma,
    get_infinity,
    get_ollama,
)

COLLECTION = "qna_smoke_test"
MINILM = "sentence-transformers/all-MiniLM-L6-v2"

failures: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


async def smoke_infinity() -> list[list[float]]:
    infinity = get_infinity()
    served = await infinity.models()
    wanted = [m for m in os.environ.get("INFINITY_MODEL_ID", MINILM).split(";") if m]
    check(
        all(m in served for m in wanted),
        "Infinity serves INFINITY_MODEL_ID",
        str(served),
    )

    texts = [
        "Each student gets three slip days for the semester.",
        "Late work uses slip days; each one extends a deadline by a day.",
        "Titration measures the concentration of an acid.",
    ]
    started = time.perf_counter()
    vectors = await infinity.embed(MINILM, texts)
    ms = (time.perf_counter() - started) * 1000
    check(
        len(vectors) == 3 and len(vectors[0]) == 384,
        "MiniLM embeds 3 texts at 384 dimensions",
        f"{ms:.0f} ms",
    )
    related, unrelated = cosine(vectors[0], vectors[1]), cosine(vectors[0], vectors[2])
    check(
        related > unrelated,
        "Related texts are closer than unrelated ones",
        f"{related:.3f} vs {unrelated:.3f}",
    )

    for model in wanted:
        if model == MINILM:
            continue
        started = time.perf_counter()
        other = await infinity.embed(model, texts[:1])
        ms = (time.perf_counter() - started) * 1000
        check(
            len(other[0]) > 0, f"{model} embeds", f"{len(other[0])} dims, {ms:.0f} ms"
        )
    return vectors


async def smoke_chroma(vectors: list[list[float]]) -> None:
    chroma = get_chroma()
    check(await chroma.heartbeat() > 0, "Chroma heartbeat")
    try:
        await chroma.delete_collection(COLLECTION)
    except RagError:
        pass  # didn't exist

    await chroma.upsert(
        COLLECTION,
        ids=["a", "b", "c"],
        embeddings=vectors,
        documents=["slip days", "late work", "titration"],
        metadatas=[
            {"course_id": 1, "resource_id": 7, "sync_id": "old"},
            {"course_id": 1, "resource_id": 7, "sync_id": "new"},
            {"course_id": 2, "resource_id": 9, "sync_id": "old"},
        ],
    )
    check(await chroma.count(COLLECTION) == 3, "Upsert stores 3 rows")

    hits = await chroma.query(
        COLLECTION, vectors[0], n_results=3, where={"course_id": 1}
    )
    check([h.id for h in hits][:1] == ["a"], "Nearest hit is the query's own row")
    check(
        all(h.metadata["course_id"] == 1 for h in hits),
        "where course_id filters rows",
        f"{len(hits)} hits",
    )
    expected = cosine(vectors[0], vectors[1])
    got = next(h.similarity for h in hits if h.id == "b")
    check(
        abs(expected - got) < 1e-3,
        "1 - distance equals cosine similarity (cosine space)",
        f"local {expected:.4f}, chroma {got:.4f}",
    )

    await chroma.delete(
        COLLECTION,
        where={"$and": [{"resource_id": 7}, {"sync_id": {"$ne": "new"}}]},
    )
    remaining = sorted(
        h.id
        for h in await chroma.query(
            COLLECTION, vectors[0], n_results=3, where={"resource_id": {"$ne": -1}}
        )
    )
    check(
        remaining == ["b", "c"],
        "$and + $ne delete removes only stale rows",
        str(remaining),
    )

    await chroma.delete_collection(COLLECTION)


async def smoke_ollama() -> None:
    ollama = get_ollama()
    pulled = await ollama.list_models()
    model = settings.RAG_DEFAULT_MODEL
    check(model in pulled, f"Ollama has {model} pulled", str(sorted(pulled)))
    try:
        await ollama.require_model("not-a-real-model:0b")
        check(False, "Unpulled model is rejected")
    except RagError as exc:
        check(exc.status_code == 422, "Unpulled model is rejected with 422")
    if model not in pulled:
        return

    system = (
        "Only use the information provided in the tagged context to answer questions. "
        "If the context does not contain enough information to answer, say so rather than guessing."
    )
    user = (
        '<context>\n<syllabus source="smoke" section="Late work">\n'
        "Each student gets three slip days for the semester.\n</syllabus>\n</context>\n\n"
        "Question: How many slip days do I get?"
    )
    options = {"temperature": 0, "seed": 42, "num_ctx": 4096}
    started = time.perf_counter()
    first = await ollama.chat(model, system, user, options)
    ms = (time.perf_counter() - started) * 1000
    second = await ollama.chat(model, system, user, options)
    check(
        bool(first.strip()),
        "Ollama chat answers",
        f"{ms:.0f} ms: {first.strip()[:80]!r}",
    )
    check(first == second, "temperature 0 + seed 42 is reproducible")


async def main() -> int:
    try:
        vectors = await smoke_infinity()
        await smoke_chroma(vectors)
        await smoke_ollama()
    except RagError as exc:
        check(False, "Service call", exc.message)
    finally:
        await close_clients()
    print(f"\n{len(failures)} failure(s)" if failures else "\nAll checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
