"""
On first startup, create the initial admin user if ADMIN_USERNAME and
ADMIN_PASSWORD are set and no ADMIN account exists yet.

This runs once inside the lifespan startup hook. After the first admin
exists the env vars are ignored — remove them from .env if you like,
or leave them (they simply become a no-op).

It also ensures the `qna-assistant` system user that authors AI answers
exists, with no password, no netid and role USER, so nobody can log in as it
(docs/design-rag.md §6.1). This runs on every startup, so bootstrap_admin
always waits for the schema; the lifespan's later startup work relies on
that.

On a fresh database the schema doesn't exist until `alembic upgrade head`
has been run, so this retries instead of crashing: startup blocks (with a
log line every few seconds) until migrations land, then completes on its
own.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError

from ..config import settings
from ..database import AsyncSessionLocal
from ..models.user import User
from .auth_service import AI_USERNAME, hash_password

logger = structlog.get_logger()

RETRY_SECONDS = 5


async def bootstrap_admin() -> None:
    create_admin = bool(settings.ADMIN_USERNAME and settings.ADMIN_PASSWORD)

    while True:
        try:
            if create_admin:
                await _create_admin_if_missing()
            await _ensure_ai_user()
            return
        except ProgrammingError:
            # Fresh database: the schema doesn't exist yet.
            logger.warning(
                "admin_bootstrap_waiting_for_schema",
                hint="run `docker compose run --rm backend alembic upgrade head` "
                "to create the schema; startup will finish on its own",
            )
        except OperationalError as exc:
            logger.warning("admin_bootstrap_retrying", error=str(exc.orig))
        await asyncio.sleep(RETRY_SECONDS)


async def _create_admin_if_missing() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.role == "ADMIN").limit(1))
        if result.scalars().first() is not None:
            return  # admin already exists

        admin = User(
            id=str(uuid.uuid4()),
            username=settings.ADMIN_USERNAME.lower(),
            display_name="Admin",
            password_hash=hash_password(settings.ADMIN_PASSWORD),
            role="ADMIN",
        )
        db.add(admin)
        await db.commit()
        logger.info("admin_bootstrapped", username=settings.ADMIN_USERNAME.lower())


async def _ensure_ai_user() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.username == AI_USERNAME).limit(1)
        )
        ai_user = result.scalars().first()
        if ai_user is None:
            db.add(
                User(
                    id=str(uuid.uuid4()),
                    username=AI_USERNAME,
                    display_name="AI Assistant",
                    password_hash=None,
                    netid=None,
                    role="USER",
                )
            )
        elif (
            ai_user.password_hash is None
            and ai_user.netid is None
            and ai_user.role == "USER"
        ):
            return
        else:
            # Someone gave it a way in; take it away again.
            ai_user.password_hash = None
            ai_user.netid = None
            ai_user.role = "USER"
        await db.commit()
        logger.info("ai_user_ready", username=AI_USERNAME)
