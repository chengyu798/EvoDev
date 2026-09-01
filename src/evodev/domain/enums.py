from enum import StrEnum


class TaskRunStatus(StrEnum):
    CREATED = "created"
    PREPARING = "preparing"
    BASELINE_TESTING = "baseline_testing"
    ANALYZING = "analyzing"
    IMPLEMENTING = "implementing"
    TESTING = "testing"
    DEBUGGING = "debugging"
    REVIEWING = "reviewing"
    FINALIZING = "finalizing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InvocationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
