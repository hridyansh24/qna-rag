"""
Integration tests for POST /rag/compare and the RAG settings endpoints
(docs/design-rag.md §9.1, §9.5, §13), against the running stack with Ollama,
Infinity and ChromaDB, and `qwen2.5:1.5b` pulled.

Reuses test_rag_ingestion's module fixture: a course with the eval sample
data uploaded and the `sliding-window` profile synced.

Run with:
    cd tests/integration && pytest test_rag_compare.py -v
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from .conftest import admin_headers, login_as_netid

GUARDRAIL = (
    "Only use the information provided in the tagged context to answer "
    "questions. If the context does not contain enough information to answer, "
    "say so rather than guessing."
)
MODEL = "qwen2.5:1.5b"


def body(**overrides) -> dict:
    b = {
        "question": "When is Project 3 due?",
        "ingestion_profile": "sliding-window",
        "similarity_threshold": 0.0,
        "system_prompt": GUARDRAIL,
        "generation_model": MODEL,
    }
    b.update(overrides)
    return b


def compare(base_url, course, headers, payload, timeout=200.0):
    return httpx.post(
        f"{base_url}/api/courses/{course}/rag/compare",
        json=payload,
        headers=headers,
        timeout=timeout,
    )


def board_snapshot(base_url, course, headers) -> dict:
    """Every question with its post count, and every ingestion run."""
    questions = httpx.get(
        f"{base_url}/api/courses/{course}/questions", headers=headers, timeout=10.0
    ).json()
    items = questions["items"] if isinstance(questions, dict) else questions
    posts = {}
    for q in items:
        detail = httpx.get(
            f"{base_url}/api/courses/{course}/questions/{q['id']}",
            headers=headers,
            timeout=10.0,
        ).json()
        posts[q["id"]] = len(detail["posts"])
    runs = httpx.get(
        f"{base_url}/api/courses/{course}/ingestion-runs", headers=headers, timeout=10.0
    ).json()
    resources = httpx.get(
        f"{base_url}/api/courses/{course}/resources", headers=headers, timeout=10.0
    ).json()
    return {
        "posts": posts,
        "runs": sorted(r["id"] for r in runs),
        "chunks": {
            r["id"]: {
                k: (v or {}).get("chunk_count") for k, v in r["latest_runs"].items()
            }
            for r in resources
        },
    }


@pytest.fixture(scope="module")
def matched(base_url, rag_course):
    """One generating call, shared by the tests that inspect its response."""
    before = board_snapshot(base_url, rag_course["id"], rag_course["staff"])
    r = compare(base_url, rag_course["id"], rag_course["staff"], body())
    after = board_snapshot(base_url, rag_course["id"], rag_course["staff"])
    return r, before, after


def test_matched_call_has_the_exact_contract_shape(matched):
    r, _, _ = matched
    assert r.status_code == 200, r.text
    data = r.json()
    assert set(data) == {"matched", "retrieved_chunks", "answer", "metrics"}
    assert data["matched"] is True
    assert isinstance(data["answer"], str) and data["answer"].strip()
    assert set(data["metrics"]) == {
        "embedding_time_ms",
        "retrieval_time_ms",
        "generation_time_ms",
        "cpu_percent",
    }
    assert data["metrics"]["generation_time_ms"] > 0
    assert 0 <= data["metrics"]["cpu_percent"] <= 100
    chunks = data["retrieved_chunks"]
    assert 1 <= len(chunks) <= 4
    for c in chunks:
        assert set(c) == {"resource_type", "source_url", "similarity_score", "text"}
    scores = [c["similarity_score"] for c in chunks]
    assert scores == sorted(scores, reverse=True)


def test_matched_call_retrieves_the_schedule_and_answers_from_it(matched):
    data = matched[0].json()
    sources = [c["source_url"] for c in data["retrieved_chunks"]]
    # The harness credits retrieval by this substring (§5.5).
    assert any("eval/sample_data/web/schedule.html" in s for s in sources), sources
    assert "27" in data["answer"], data["answer"]


def test_compare_is_a_dry_run(matched):
    _, before, after = matched
    assert after == before


def test_threshold_above_every_chunk_is_unmatched_with_no_generation(
    base_url, rag_course
):
    r = compare(
        base_url, rag_course["id"], rag_course["staff"], body(similarity_threshold=1.0)
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["matched"] is False
    assert data["answer"] is None
    assert data["retrieved_chunks"] == []
    assert data["metrics"]["generation_time_ms"] == 0


def test_returned_chunks_all_clear_the_threshold(base_url, rag_course):
    r = compare(
        base_url,
        rag_course["id"],
        rag_course["staff"],
        # High enough that only close chunks survive, so nothing generates
        # unless one does.
        body(similarity_threshold=0.99, question="zzzz qqqq unrelated"),
    )
    assert r.status_code == 200, r.text
    assert all(c["similarity_score"] >= 0.99 for c in r.json()["retrieved_chunks"])


def test_unknown_profile_is_404(base_url, rag_course):
    r = compare(
        base_url,
        rag_course["id"],
        rag_course["staff"],
        body(ingestion_profile="no-such"),
    )
    assert r.status_code == 404, r.text
    assert r.json()["error"] == "PROFILE_NOT_FOUND"


def test_profile_never_ingested_is_409(base_url, rag_course):
    staff = rag_course["staff"]
    presets = httpx.get(
        f"{base_url}/api/courses/{rag_course['id']}/profiles/presets",
        headers=staff,
        timeout=10.0,
    ).json()
    preset = dict(next(p for p in presets if p["name"] == "type-tailored"))
    preset["name"] = f"empty-{uuid.uuid4().hex[:6]}"
    r = httpx.post(
        f"{base_url}/api/courses/{rag_course['id']}/profiles",
        json=preset,
        headers=staff,
        timeout=10.0,
    )
    assert r.status_code == 201, r.text
    r = compare(
        base_url, rag_course["id"], staff, body(ingestion_profile=preset["name"])
    )
    assert r.status_code == 409, r.text


def test_model_not_pulled_is_422_never_a_fallback(base_url, rag_course):
    r = compare(
        base_url,
        rag_course["id"],
        rag_course["staff"],
        body(generation_model="not-a-model:0.1b"),
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"] == "MODEL_NOT_AVAILABLE"


@pytest.mark.parametrize(
    "payload",
    [
        body(similarity_threshold=1.5),
        body(similarity_threshold=-0.1),
        body(question=""),
        body(system_prompt=""),
        body(extra_field=True),
        {k: v for k, v in body().items() if k != "generation_model"},
    ],
)
def test_invalid_requests_are_422(base_url, rag_course, payload):
    r = compare(base_url, rag_course["id"], rag_course["staff"], payload, timeout=10.0)
    assert r.status_code == 422, r.text


def test_compare_requires_course_staff(base_url, admin_token, rag_course):
    course = rag_course["id"]
    student = {
        "Authorization": f"Bearer {login_as_netid(base_url, admin_token, course, 'STUDENT')}"
    }
    assert compare(base_url, course, student, body(), timeout=10.0).status_code == 403
    assert compare(base_url, course, {}, body(), timeout=10.0).status_code == 401
    # Staff of another course can't see this one at all.
    other = httpx.post(
        f"{base_url}/api/admin/courses",
        json={"name": f"Other {uuid.uuid4().hex[:8]}", "semester": "Test"},
        headers=admin_headers(admin_token),
        timeout=10.0,
    ).json()["id"]
    outsider = {
        "Authorization": f"Bearer {login_as_netid(base_url, admin_token, other, 'STAFF')}"
    }
    assert compare(base_url, course, outsider, body(), timeout=10.0).status_code == 404


def test_admin_passes_the_staff_guard(base_url, admin_token, rag_course):
    r = compare(
        base_url,
        rag_course["id"],
        admin_headers(admin_token),
        body(similarity_threshold=1.0),
        timeout=30.0,
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# /rag/settings
# ---------------------------------------------------------------------------


def settings_url(base_url, course):
    return f"{base_url}/api/courses/{course}/rag/settings"


def test_settings_default_then_round_trip(base_url, rag_course):
    url, staff = settings_url(base_url, rag_course["id"]), rag_course["staff"]
    r = httpx.get(url, headers=staff, timeout=10.0)
    assert r.status_code == 200, r.text
    current = r.json()
    assert set(current) == {
        "enabled",
        "active_profile",
        "similarity_threshold",
        "system_prompt",
        "generation_model",
    }
    assert "INSUFFICIENT_CONTEXT" in current["system_prompt"]

    new = dict(current, similarity_threshold=0.42, enabled=False)
    r = httpx.put(url, json=new, headers=staff, timeout=30.0)
    assert r.status_code == 200, r.text
    assert r.json() == new
    assert httpx.get(url, headers=staff, timeout=10.0).json() == new
    httpx.put(url, json=current, headers=staff, timeout=30.0)


def test_settings_reject_unknown_profile_and_unpulled_model(base_url, rag_course):
    url, staff = settings_url(base_url, rag_course["id"]), rag_course["staff"]
    current = httpx.get(url, headers=staff, timeout=10.0).json()
    r = httpx.put(
        url, json=dict(current, active_profile="no-such"), headers=staff, timeout=30.0
    )
    assert r.status_code == 422, r.text
    r = httpx.put(
        url,
        json=dict(current, generation_model="not-a-model:0.1b"),
        headers=staff,
        timeout=30.0,
    )
    assert r.status_code == 422, r.text
    assert httpx.get(url, headers=staff, timeout=10.0).json() == current


def test_settings_require_course_staff(base_url, admin_token, rag_course):
    course = rag_course["id"]
    student = {
        "Authorization": f"Bearer {login_as_netid(base_url, admin_token, course, 'STUDENT')}"
    }
    url = settings_url(base_url, course)
    assert httpx.get(url, headers=student, timeout=10.0).status_code == 403
    current = httpx.get(url, headers=rag_course["staff"], timeout=10.0).json()
    assert (
        httpx.put(url, json=current, headers=student, timeout=10.0).status_code == 403
    )
