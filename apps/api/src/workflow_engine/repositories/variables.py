from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from workflow_engine.models import Variable
from workflow_engine.repositories.base import Repository


class VariableRepository(Repository):
    async def all(self, workspace_id: uuid.UUID) -> list[Variable]:
        result = await self.session.execute(
            select(Variable).where(Variable.workspace_id == workspace_id).order_by(Variable.key)
        )
        return list(result.scalars())

    async def as_dict(self, workspace_id: uuid.UUID) -> dict[str, str]:
        result = await self.session.execute(
            select(Variable.key, Variable.value).where(Variable.workspace_id == workspace_id)
        )
        return {str(key): str(value) for key, value in result.tuples()}

    async def upsert(
        self,
        workspace_id: uuid.UUID,
        key: str,
        value: str,
        description: str,
        user_id: uuid.UUID | None,
    ) -> Variable:
        statement = (
            insert(Variable)
            .values(
                workspace_id=workspace_id,
                key=key,
                value=value,
                description=description,
                updated_by=user_id,
            )
            .on_conflict_do_update(
                index_elements=[Variable.workspace_id, Variable.key],
                set_={"value": value, "description": description, "updated_by": user_id},
            )
            .returning(Variable)
        )
        result = await self.session.execute(statement)
        return result.scalar_one()

    async def remove(self, workspace_id: uuid.UUID, key: str) -> bool:
        result = await self.session.execute(
            delete(Variable)
            .where(Variable.workspace_id == workspace_id, Variable.key == key)
            .returning(Variable.key)
        )
        return result.scalar_one_or_none() is not None
