"""Operator command line.

wfe migrate
wfe user create --email you@example.com --name "You" --admin
wfe worker [--no-scheduler]
wfe demo-apis --port 9131
wfe demo seed
wfe openapi --out docs/api/openapi.json
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer

from workflow_engine.core.config import get_settings
from workflow_engine.core.logging import configure_logging

app = typer.Typer(
    no_args_is_help=True, help="Euron WorkflowEngine command line.", add_completion=False
)
user_app = typer.Typer(no_args_is_help=True, help="Manage accounts.")
demo_app = typer.Typer(no_args_is_help=True, help="Demo data for local stacks.")
app.add_typer(user_app, name="user")
app.add_typer(demo_app, name="demo")


@app.callback()
def _setup() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, "console")


@app.command()
def migrate() -> None:
    """Apply pending database migrations."""
    from workflow_engine.db.migrate import migrate as run

    asyncio.run(run(get_settings()))
    typer.echo("migrations applied")


@user_app.command("create")
def create_user(
    email: Annotated[str, typer.Option(help="Sign-in email.")],
    name: Annotated[str, typer.Option(help="Display name.")],
    password: Annotated[str, typer.Option(prompt=True, hide_input=True, confirmation_prompt=True)],
    admin: Annotated[bool, typer.Option(help="Instance administrator.")] = False,
) -> None:
    """Create an account."""
    from workflow_engine.db.session import Database
    from workflow_engine.services.users import create_user as create

    async def run() -> None:
        db = Database(get_settings())
        try:
            async with db.session() as session:
                user = await create(
                    session, email=email, name=name, password=password, is_admin=admin
                )
                typer.echo(f"created {user.email} ({user.id})")
        finally:
            await db.dispose()

    asyncio.run(run())


@app.command()
def worker(
    scheduler: Annotated[
        bool | None,
        typer.Option(
            "--scheduler/--no-scheduler",
            help="Take part in the scheduler leader election (default: SCHEDULER_ENABLED).",
        ),
    ] = None,
) -> None:
    """Run a worker: claim and execute steps (and schedule, when elected)."""
    from workflow_engine.worker import main

    main(scheduler_enabled=scheduler)


@app.command("demo-apis")
def demo_apis(
    host: Annotated[str, typer.Option(help="Interface to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to listen on.")] = 9131,
) -> None:
    """Serve the deterministic Northwind demo APIs used by the templates."""
    import uvicorn

    from workflow_engine.demo.apis import create_app

    uvicorn.run(create_app(), host=host, port=port, log_level="warning")


@demo_app.command("seed")
def seed(
    password: Annotated[
        str | None, typer.Option(envvar="DEMO_PASSWORD", help="Password for every demo account.")
    ] = None,
    history_days: Annotated[int, typer.Option(help="Days of execution history to spread.")] = 14,
) -> None:
    """Demo accounts, a workspace, credentials, the template workflows and real history."""
    from workflow_engine.demo.seed import run

    settings = get_settings()
    if settings.is_production:
        raise typer.BadParameter("refusing to seed demo data with APP_ENV=production")
    secret = password or (
        settings.demo_password.get_secret_value() if settings.demo_password else None
    )
    if not secret:
        raise typer.BadParameter("set DEMO_PASSWORD (make env generates one)")
    asyncio.run(run(settings, secret, history_days=history_days))


@app.command()
def openapi(
    out: Annotated[Path, typer.Option(help="Where to write the OpenAPI document.")] = Path(
        "openapi.json"
    ),
    check: Annotated[
        bool, typer.Option(help="Fail if the file differs instead of writing.")
    ] = False,
) -> None:
    """Export the OpenAPI document generated from the routes."""
    from workflow_engine.main import create_app

    document = json.dumps(create_app().openapi(), indent=2, sort_keys=False) + "\n"
    if check:
        current = out.read_text() if out.exists() else ""
        if current != document:
            typer.echo(f"{out} is out of date: run make openapi", err=True)
            raise typer.Exit(1)
        typer.echo(f"{out} is up to date")
        return
    out.write_text(document)
    typer.echo(f"wrote {out}")


if __name__ == "__main__":
    app()
