"""Request dependencies: infrastructure, the caller, workspace access and rate limits."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, Path, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from workflow_engine.core.config import Settings
from workflow_engine.core.errors import ForbiddenError, RateLimitedError, UnauthorizedError
from workflow_engine.models import User, Workspace
from workflow_engine.models.enums import Role
from workflow_engine.services.api_keys import ApiKeyService
from workflow_engine.services.auth import SESSION_COOKIE, AuthService
from workflow_engine.services.container import Container
from workflow_engine.services.principal import Principal
from workflow_engine.services.workspaces import WorkspaceService, require_role

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


def get_settings_dep(container: ContainerDep) -> Settings:
    return container.settings


async def get_session(container: ContainerDep) -> AsyncIterator[AsyncSession]:
    async with container.db.session() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _origin_allowed(request: Request, settings: Settings) -> bool:
    """CSRF defence for cookie sessions: unsafe methods must come from our own web app."""
    origin = request.headers.get("origin")
    if origin is None and (referer := request.headers.get("referer")):
        parts = urlsplit(referer)
        origin = f"{parts.scheme}://{parts.netloc}"
    allowed = {*settings.cors_origins, settings.web_url.rstrip("/")}
    return origin in allowed


async def get_principal(
    request: Request, container: ContainerDep, session: SessionDep
) -> Principal:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token.startswith("wfk_"):
            return Principal(api_key=await ApiKeyService(container, session).resolve(token))
        user, claims = await AuthService(container, session).resolve(token)
        return Principal(user=user, session=claims)
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        user, claims = await AuthService(container, session).resolve(cookie)
        if request.method not in _SAFE_METHODS and not _origin_allowed(request, container.settings):
            raise ForbiddenError("Cross-site request blocked.", code="csrf")
        return Principal(user=user, session=claims, via_cookie=True)
    raise UnauthorizedError()


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def get_user(principal: PrincipalDep) -> User:
    if principal.user is None:
        raise ForbiddenError("This needs a signed-in person, not an API key.")
    return principal.user


UserDep = Annotated[User, Depends(get_user)]


@dataclass(frozen=True, slots=True)
class WorkspaceContext:
    workspace: Workspace
    role: Role
    principal: Principal

    @property
    def id(self) -> uuid.UUID:
        return self.workspace.id


class WorkspaceAccess:
    """Resolve `{workspace}` (id or slug) and require at least `minimum` role in it."""

    def __init__(self, minimum: Role) -> None:
        self.minimum = minimum

    async def __call__(
        self,
        workspace: Annotated[str, Path(description="Workspace id or slug.", max_length=64)],
        principal: PrincipalDep,
        container: ContainerDep,
        session: SessionDep,
    ) -> WorkspaceContext:
        resolved, role = await WorkspaceService(container, session).resolve(principal, workspace)
        require_role(role, self.minimum)
        return WorkspaceContext(resolved, role, principal)


ViewerDep = Annotated[WorkspaceContext, Depends(WorkspaceAccess(Role.VIEWER))]
EditorDep = Annotated[WorkspaceContext, Depends(WorkspaceAccess(Role.EDITOR))]
OwnerDep = Annotated[WorkspaceContext, Depends(WorkspaceAccess(Role.OWNER))]


def rate_limit(bucket: str, setting: str) -> Callable[..., Awaitable[None]]:
    async def dependency(
        response: Response, principal: PrincipalDep, container: ContainerDep
    ) -> None:
        result = await container.limiter.hit(
            f"{bucket}:{principal.rate_key}", getattr(container.settings, setting)
        )
        response.headers.update(result.headers())
        if not result.allowed:
            raise RateLimitedError(headers={"retry-after": str(result.reset_s), **result.headers()})

    return dependency


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
