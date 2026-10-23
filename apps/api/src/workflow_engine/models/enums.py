"""Value sets stored as text with CHECK constraints (cheaper to evolve than Postgres enums)."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"

    @property
    def rank(self) -> int:
        return {Role.VIEWER: 1, Role.EDITOR: 2, Role.OWNER: 3}[self]

    def allows(self, required: Role) -> bool:
        return self.rank >= required.rank


class ExecutionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {
            ExecutionStatus.SUCCEEDED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
        }


class StepStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


ACTIVE_STEP_STATUSES = (StepStatus.QUEUED, StepStatus.RUNNING, StepStatus.WAITING)


class ExecutionMode(StrEnum):
    PRODUCTION = "production"  # a trigger of an active workflow
    MANUAL = "manual"  # "Run" on the published version, from the API or the web app
    TEST = "test"  # the editor ran the draft


class TriggerKind(StrEnum):
    MANUAL = "manual"
    WEBHOOK = "webhook"
    CRON = "cron"
    INTERVAL = "interval"
    EVENT = "event"
    RETRY = "retry"


class VersionKind(StrEnum):
    PUBLISHED = "published"
    SNAPSHOT = "snapshot"


class DeadLetterStatus(StrEnum):
    OPEN = "open"
    RETRIED = "retried"
    DISCARDED = "discarded"


class EventSource(StrEnum):
    API = "api"
    WORKFLOW = "workflow"
    SYSTEM = "system"


class LogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class KeyProvider(StrEnum):
    KMS = "kms"
    LOCAL = "local"
