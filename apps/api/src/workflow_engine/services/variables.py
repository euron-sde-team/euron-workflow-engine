"""Workspace variables: non-secret settings that templates read as `env.KEY`."""

from __future__ import annotations

import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from workflow_engine.core.errors import NotFoundError, UnprocessableError
from workflow_engine.models import Variable
from workflow_engine.repositories.variables import VariableRepository
from workflow_engine.schemas.variables import VARIABLE_KEY
from workflow_engine.services import audit
from workflow_engine.services.principal import Principal

_KEY = re.compile(VARIABLE_KEY)


class VariableService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.variables = VariableRepository(session)

    async def all(self, workspace_id: uuid.UUID) -> list[Variable]:
        return await self.variables.all(workspace_id)

    async def put(
        self, workspace_id: uuid.UUID, principal: Principal, key: str, value: str, description: str
    ) -> Variable:
        if not _KEY.match(key):
            raise UnprocessableError(
                "Variable names are upper case letters, digits and underscores, like SHOP_API."
            )
        variable = await self.variables.upsert(
            workspace_id, key, value, description.strip(), principal.user_id
        )
        await audit.record(
            self.session,
            workspace_id=workspace_id,
            principal=principal,
            action="variable.saved",
            target_type="variable",
            target_id=key,
        )
        await self.session.commit()
        return variable

    async def delete(self, workspace_id: uuid.UUID, principal: Principal, key: str) -> None:
        if not await self.variables.remove(workspace_id, key):
            raise NotFoundError("Variable not found.")
        await audit.record(
            self.session,
            workspace_id=workspace_id,
            principal=principal,
            action="variable.deleted",
            target_type="variable",
            target_id=key,
        )
        await self.session.commit()
