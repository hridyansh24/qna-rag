"""
Unit tests for how AI posts, hidden posts and citations are serialized
(docs/design-rag.md §6.1, §6.2, §6.5).

No Docker stack required: questions and posts are plain stand-ins.

Run with:
    cd tests/unit && pytest test_rag_serialization.py -v
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from app.common.exceptions import ConflictError
from app.schemas.qa import QuestionDetail, QuestionSummary
from app.services import qa_service

NOW = datetime(2026, 10, 26, 12, 0)
ALICE = SimpleNamespace(id="u-alice", display_name="Alice", username=None, netid=None)
BOT = SimpleNamespace(
    id="u-ai", display_name="AI Assistant", username="qna-assistant", netid=None
)


def citation(rank=1):
    return SimpleNamespace(
        rank=rank,
        resource_id=3,
        resource_type="repo_markdown",
        label="Course repository: p2-buzzer/instructions.md, lines 10–25",
        citation_url="/student/sources/3/eval/sample_data/repo/p2-buzzer/instructions.md?lines=10-25",
        location_json={"lines": [10, 25]},
        quoted_text="The CI pipeline runs lint and tests.",
        similarity_score=0.71,
    )


def post(
    pid,
    author=ALICE,
    role="STUDENT",
    kind="ANSWER",
    accepted=False,
    hidden=False,
    citations=(),
):
    return SimpleNamespace(
        id=pid,
        question_id=7,
        author=author,
        author_role=role,
        kind=kind,
        body=f"post {pid}",
        is_accepted=accepted,
        accepted_by=None,
        accepted_at=None,
        is_hidden=hidden,
        citations=list(citations),
        created_at=NOW,
    )


def question(*posts, ai_status="ANSWERED"):
    return SimpleNamespace(
        id=7,
        course_id=1,
        title="What does CI check?",
        body="Before approval.",
        status="OPEN",
        author=ALICE,
        category_links=[],
        posts=list(posts),
        ai_status=ai_status,
        closed_by=None,
        closed_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


def test_ai_post_carries_its_citations_and_flags():
    q = question(post(1, author=BOT, role="AI", citations=[citation(1), citation(2)]))
    detail = QuestionDetail(**qa_service.serialize_question_detail(q, "STAFF"))
    ai = detail.posts[0]
    assert ai.author_role == "AI" and ai.is_hidden is False
    assert [c.rank for c in ai.citations] == [1, 2]
    assert ai.citations[0].location == {"lines": [10, 25]}
    assert detail.ai_status == "ANSWERED"


def test_students_never_see_hidden_posts():
    q = question(post(1), post(2, author=BOT, role="AI", accepted=True, hidden=True))
    detail = QuestionDetail(**qa_service.serialize_question_detail(q, "STUDENT"))
    summary = QuestionSummary(**qa_service.serialize_question_summary(q, "STUDENT"))
    assert [p.id for p in detail.posts] == [1]
    assert (summary.post_count, summary.has_accepted_answer, summary.has_ai_answer) == (
        1,
        False,
        False,
    )


def test_staff_see_hidden_posts():
    q = question(post(1), post(2, author=BOT, role="AI", hidden=True))
    detail = QuestionDetail(**qa_service.serialize_question_detail(q, "STAFF"))
    summary = QuestionSummary(**qa_service.serialize_question_summary(q, "STAFF"))
    assert [p.id for p in detail.posts] == [1, 2] and detail.posts[1].is_hidden
    assert (summary.post_count, summary.has_ai_answer) == (2, True)


async def test_accepting_a_hidden_post_is_refused():
    q = question(post(1, author=BOT, role="AI", hidden=True))
    with (
        patch.object(qa_service, "_get_question", AsyncMock(return_value=q)),
        pytest.raises(ConflictError),
    ):
        await qa_service.set_post_accepted(AsyncMock(), 1, 7, 1, ALICE, True)
    assert q.posts[0].is_accepted is False


async def test_unaccepting_a_hidden_post_is_allowed():
    q = question(post(1, author=BOT, role="AI", accepted=True, hidden=True))
    with patch.object(qa_service, "_get_question", AsyncMock(return_value=q)):
        await qa_service.set_post_accepted(AsyncMock(), 1, 7, 1, ALICE, False)
    assert q.posts[0].is_accepted is False


async def test_hiding_an_accepted_ai_post_unaccepts_it():
    q = question(post(1, author=BOT, role="AI", accepted=True))
    with patch.object(qa_service, "_get_question", AsyncMock(return_value=q)):
        await qa_service.set_post_hidden(AsyncMock(), 1, 7, 1, True)
    assert q.posts[0].is_hidden is True and q.posts[0].is_accepted is False


async def test_unhiding_leaves_the_post_unaccepted():
    q = question(post(1, author=BOT, role="AI", hidden=True))
    with patch.object(qa_service, "_get_question", AsyncMock(return_value=q)):
        await qa_service.set_post_hidden(AsyncMock(), 1, 7, 1, False)
    assert q.posts[0].is_hidden is False and q.posts[0].is_accepted is False


@pytest.mark.parametrize("role", ["STUDENT", "STAFF"])
async def test_hiding_a_human_post_is_refused(role):
    q = question(post(1, role=role))
    with (
        patch.object(qa_service, "_get_question", AsyncMock(return_value=q)),
        pytest.raises(ConflictError),
    ):
        await qa_service.set_post_hidden(AsyncMock(), 1, 7, 1, True)
    assert q.posts[0].is_hidden is False
