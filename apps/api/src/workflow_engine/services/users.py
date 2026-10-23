"""Account administration used by the CLI and the demo seed."""

from __future__ import annotations

import anyio
from sqlalchemy.ext.asyncio import AsyncSession

from workflow_engine.core.errors import ConflictError
from workflow_engine.core.security import hash_password, validate_password
from workflow_engine.models import User
from workflow_engine.repositories.users import UserRepository


async def create_user(
    session: AsyncSession, *, email: str, name: str, password: str, is_admin: bool = False
) -> User:
    users = UserRepository(session)
    if await users.by_email(email):
        raise ConflictError("An account with that email already exists.")
    validate_password(password, email=email)
    user = await users.add(
        User(
            email=email.strip().lower(),
            name=name.strip(),
            password_hash=await anyio.to_thread.run_sync(hash_password, password),
            is_admin=is_admin,
        )
    )
    await session.commit()
    return user
