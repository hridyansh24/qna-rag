"""
Integration tests for the auto-responder (docs/design-rag.md §6, §13),
against the running stack with Ollama, Infinity and ChromaDB, and
`qwen2.5:1.5b` pulled.

Uses the shared `rag_course` fixture (conftest.py): the eval sample data
uploaded and the `sliding-window` profile synced. The course's live
settings start at the defaults: enabled, `sliding-window`, the calibrated
threshold, the sentinel prompt, `qwen2.5:1.5b`.

Run with:
    cd tests/integration && pytest test_rag_auto_answer.py -v
"""

from __future__ import annotations

import time

import httpx
import pytest

from .conftest import login_as_netid

ANSWER_TIMEOUT_S = 240


def ask(base_url, course, headers, category, title, body) -> dict:
    r = httpx.post(
        f"{base_url}/api/courses/{course}/questions",
        json={"title": title, "body": body, "category_ids": [category]},
        headers=headers,
        timeout=10.0,
    )
    assert r.status_code == 201, r.text
    return r.json()


def get_question(base_url, course, headers, qid) -> dict:
    r = httpx.get(
        f"{base_url}/api/courses/{course}/questions/{qid}",
        headers=headers,
        timeout=10.0,
    )
    assert r.status_code == 200, r.text
    return r.json()


def wait_answered(base_url, course, headers, qid) -> dict:
    deadline = time.monotonic() + ANSWER_TIMEOUT_S
    while True:
        q = get_question(base_url, course, headers, qid)
        if q["ai_status"] != "PENDING":
            return q
        assert time.monotonic() < deadline, f"question {qid} still PENDING"
        time.sleep(2)


def ai_posts(question: dict) -> list[dict]:
    return [p for p in question["posts"] if p["author_role"] == "AI"]


@pytest.fixture(scope="module")
def student(base_url, admin_token, rag_course):
    token = login_as_netid(base_url, admin_token, rag_course["id"], "STUDENT")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def category(base_url, rag_course):
    r = httpx.post(
        f"{base_url}/api/courses/{rag_course['id']}/categories",
        json={"name": "Auto-responder"},
        headers=rag_course["staff"],
        timeout=10.0,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def answered(base_url, rag_course, student, category):
    """A student asks a question the schedule answers."""
    q = ask(
        base_url,
        rag_course["id"],
        student,
        category,
        "When is Project 3 due?",
        "What is the exact deadline for P3?",
    )
    assert q["ai_status"] == "PENDING"
    return wait_answered(base_url, rag_course["id"], student, q["id"])


def test_matched_question_gets_one_labeled_ai_answer(answered):
    assert answered["ai_status"] == "ANSWERED", answered
    (post,) = ai_posts(answered)
    assert post["kind"] == "ANSWER"
    assert post["body"].strip()
    assert post["author"]["display_name"] == "AI Assistant"
    # Visible to the student who asked, with no staff pre-approval.
    assert post["is_accepted"] is False


def test_ai_answer_cites_its_grounding_source(base_url, rag_course, answered):
    (post,) = ai_posts(answered)
    cites = post["citations"]
    assert 1 <= len(cites) <= 4
    assert [c["rank"] for c in cites] == list(range(1, len(cites) + 1))
    assert len({c["citation_url"] for c in cites}) == len(cites)
    schedule = [c for c in cites if c["resource_type"] == "schedule"]
    assert schedule, cites
    c = schedule[0]
    assert c["citation_url"].startswith(
        f"/student/sources/{rag_course['uploaded']['SCHEDULE']['id']}/"
    )
    assert "chars=" in c["citation_url"]
    assert set(c["location"]) >= {"text_start", "text_end", "chars"}
    assert c["quoted_text"]
    assert any("27" in x["quoted_text"] for x in cites)


def test_staff_accept_an_ai_answer_through_the_existing_route(
    base_url, rag_course, answered
):
    (post,) = ai_posts(answered)
    r = httpx.patch(
        f"{base_url}/api/courses/{rag_course['id']}/questions/{answered['id']}"
        f"/posts/{post['id']}/accept",
        json={"is_accepted": True},
        headers=rag_course["staff"],
        timeout=10.0,
    )
    assert r.status_code == 200, r.text
    (accepted,) = ai_posts(r.json())
    assert accepted["is_accepted"] is True


def test_students_cannot_accept_an_ai_answer(base_url, rag_course, student, answered):
    (post,) = ai_posts(answered)
    r = httpx.patch(
        f"{base_url}/api/courses/{rag_course['id']}/questions/{answered['id']}"
        f"/posts/{post['id']}/accept",
        json={"is_accepted": False},
        headers=student,
        timeout=10.0,
    )
    assert r.status_code == 403, r.text


def hide(base_url, course, qid, pid, headers, is_hidden) -> httpx.Response:
    return httpx.patch(
        f"{base_url}/api/courses/{course}/questions/{qid}/posts/{pid}/hide",
        json={"is_hidden": is_hidden},
        headers=headers,
        timeout=10.0,
    )


def test_students_cannot_hide_an_ai_answer(base_url, rag_course, student, answered):
    (post,) = ai_posts(answered)
    r = hide(base_url, rag_course["id"], answered["id"], post["id"], student, True)
    assert r.status_code == 403, r.text


def test_staff_hide_an_ai_answer_from_students(base_url, rag_course, student, answered):
    # Runs after the accept test above, so this also checks the un-accept.
    cid, qid = rag_course["id"], answered["id"]
    (post,) = ai_posts(answered)
    r = hide(base_url, cid, qid, post["id"], rag_course["staff"], True)
    assert r.status_code == 200, r.text
    (hidden,) = ai_posts(r.json())
    assert hidden["is_hidden"] is True and hidden["is_accepted"] is False

    assert ai_posts(get_question(base_url, cid, student, qid)) == []
    r = httpx.get(
        f"{base_url}/api/courses/{cid}/questions", headers=student, timeout=10.0
    )
    assert r.status_code == 200, r.text
    (summary,) = [q for q in r.json() if q["id"] == qid]
    assert summary["has_ai_answer"] is False

    r = hide(base_url, cid, qid, post["id"], rag_course["staff"], False)
    assert r.status_code == 200, r.text
    assert len(ai_posts(get_question(base_url, cid, student, qid))) == 1


def test_staff_cannot_hide_a_human_post(base_url, rag_course, student, answered):
    cid, qid = rag_course["id"], answered["id"]
    r = httpx.post(
        f"{base_url}/api/courses/{cid}/questions/{qid}/posts",
        json={"kind": "FOLLOWUP", "body": "Thanks!"},
        headers=student,
        timeout=10.0,
    )
    assert r.status_code == 201, r.text
    human = [p for p in r.json()["posts"] if p["author_role"] == "STUDENT"][-1]
    r = hide(base_url, cid, qid, human["id"], rag_course["staff"], True)
    assert r.status_code == 409, r.text


def test_unrelated_question_is_left_for_a_human(
    base_url, rag_course, student, category
):
    q = ask(
        base_url,
        rag_course["id"],
        student,
        category,
        "What's the best pizza topping?",
        "Pineapple or not?",
    )
    q = wait_answered(base_url, rag_course["id"], student, q["id"])
    assert q["ai_status"] == "NO_MATCH"
    assert ai_posts(q) == []


def test_staff_answer_first_means_no_ai_answer(base_url, rag_course, category):
    staff = rag_course["staff"]
    q = ask(
        base_url,
        rag_course["id"],
        staff,
        category,
        "How many slip days does each student get?",
        "And what do they cover?",
    )
    r = httpx.post(
        f"{base_url}/api/courses/{rag_course['id']}/questions/{q['id']}/posts",
        json={"kind": "ANSWER", "body": "Five, for P1–P4."},
        headers=staff,
        timeout=10.0,
    )
    assert r.status_code == 201, r.text
    q = wait_answered(base_url, rag_course["id"], staff, q["id"])
    assert q["ai_status"] == "SKIPPED"
    assert ai_posts(q) == []


def test_disabled_course_gets_no_ai_answer(base_url, rag_course, student, category):
    url = f"{base_url}/api/courses/{rag_course['id']}/rag/settings"
    staff = rag_course["staff"]
    current = httpx.get(url, headers=staff, timeout=10.0).json()
    r = httpx.put(url, json=dict(current, enabled=False), headers=staff, timeout=30.0)
    assert r.status_code == 200, r.text
    try:
        q = ask(
            base_url,
            rag_course["id"],
            student,
            category,
            "When is Project 3 due?",
            "P3?",
        )
        assert q["ai_status"] == "DISABLED"
        time.sleep(2)
        q = get_question(base_url, rag_course["id"], student, q["id"])
        assert q["ai_status"] == "DISABLED" and ai_posts(q) == []
    finally:
        httpx.put(url, json=current, headers=staff, timeout=30.0)


def test_course_without_an_ingested_profile_is_not_ready(
    base_url, course_id, student_token, category_id
):
    headers = {"Authorization": f"Bearer {student_token}"}
    q = ask(base_url, course_id, headers, category_id, "When is Project 3 due?", "P3?")
    q = wait_answered(base_url, course_id, headers, q["id"])
    assert q["ai_status"] == "NOT_READY"
    assert ai_posts(q) == []
