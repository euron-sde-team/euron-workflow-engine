from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class Repository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
