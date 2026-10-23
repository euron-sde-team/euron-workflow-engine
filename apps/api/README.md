# WorkflowEngine API, workers and scheduler

FastAPI service for Euron WorkflowEngine, plus the worker process (step executor and
leader-elected scheduler) that runs from the same image with a different command.

```bash
uv sync                                         # Python 3.12 and every dependency
uv run uvicorn workflow_engine.main:create_app --factory --reload --port 8130
uv run wfe worker                               # executor + scheduler candidate
uv run wfe --help                               # CLI: migrations, users, demo data, openapi
uv run pytest tests/unit                        # unit tests, no services needed
```
