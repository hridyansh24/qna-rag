"""
Unit tests for the `qna-assistant` system user that authors AI answers
(docs/design-rag.md §6.1): bootstrap creates it with no way in, login is
refused by name, and the admin routes can't give it one.

No Docker stack required: the database session is replaced by a fake.

Run with:
    cd tests/unit && pytest test_rag_ai_user.py -v
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.common.exceptions import ConflictError
from app.routers import admin
from app.schemas.admin import UserUpdate
from app.services import auth_service, bootstrap
from app.services.auth_service import AI_USERNAME


def fake_session(existing):
    """An AsyncSessionLocal stand-in whose one query returns `existing`."""
    result = MagicMock()
    result.scalars.return_value.first.return_value = existing
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=db)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory, db


async def test_ai_user_is_created_without_any_way_to_log_in():
    factory, db = fake_session(existing=None)
    with patch.object(bootstrap, "AsyncSessionLocal", factory):
        await bootstrap._ensure_ai_user()
    user = db.add.call_args.args[0]
    assert (user.username, user.display_name, user.role) == (
        AI_USERNAME,
        "AI Assistant",
        "USER",
    )
    assert user.password_hash is None and user.netid is None
    db.commit.assert_awaited_once()


async def test_existing_ai_user_left_alone_when_locked():
    ai_user = MagicMock(password_hash=None, netid=None, role="USER")
    factory, db = fake_session(existing=ai_user)
    with patch.object(bootstrap, "AsyncSessionLocal", factory):
        await bootstrap._ensure_ai_user()
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


async def test_ai_user_given_a_password_or_role_is_locked_again():
    ai_user = MagicMock(password_hash="$2b$12$sneaky", netid="someone", role="ADMIN")
    factory, db = fake_session(existing=ai_user)
    with patch.object(bootstrap, "AsyncSessionLocal", factory):
        await bootstrap._ensure_ai_user()
    assert (ai_user.password_hash, ai_user.netid, ai_user.role) == (None, None, "USER")
    db.commit.assert_awaited_once()


async def test_bootstrap_ensures_ai_user_even_without_admin_settings():
    with (
        patch.object(bootstrap.settings, "ADMIN_USERNAME", ""),
        patch.object(bootstrap.settings, "ADMIN_PASSWORD", ""),
        patch.object(bootstrap, "_ensure_ai_user", AsyncMock()) as ensure,
    ):
        await bootstrap.bootstrap_admin()
    ensure.assert_awaited_once()


@pytest.mark.parametrize("name", [AI_USERNAME, AI_USERNAME.upper()])
async def test_login_as_ai_user_is_refused_whatever_its_hash(name):
    lookup = AsyncMock()
    with patch.object(auth_service, "get_user_by_username", lookup):
        assert (
            await auth_service.authenticate_local(MagicMock(), name, "anything") is None
        )
    lookup.assert_not_awaited()


def admin_db_with(user):
    db = MagicMock()
    db.get = AsyncMock(return_value=user)
    db.delete = AsyncMock()
    return db


async def test_admin_cannot_give_ai_user_a_password():
    ai_user = MagicMock(username=AI_USERNAME, role="USER", password_hash=None)
    with pytest.raises(ConflictError):
        await admin.update_user(
            "ai-id",
            UserUpdate(password="a-long-password"),
            MagicMock(),
            admin_db_with(ai_user),
        )
    assert ai_user.password_hash is None


async def test_admin_cannot_delete_ai_user():
    ai_user = MagicMock(username=AI_USERNAME, role="USER")
    db = admin_db_with(ai_user)
    with pytest.raises(ConflictError):
        await admin.delete_user("ai-id", MagicMock(), db)
    db.delete.assert_not_awaited()
