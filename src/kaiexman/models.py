"""Pydantic models for Kai-Exman experiment data.

Defines the core data structures used for experiment metadata and
metrics logging, enforcing validation and serialization through
Pydantic v2.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class LockedExperimentError(RuntimeError):
    """Raised when an operation is requested on an experiment that has
    already reached a terminal state and been sealed.
    """


class Attempt(BaseModel):
    """A single execution attempt within an experiment.

    Attributes:
        sequence: Attempt number (1, 2, 3...).
        start_time: ISO 8601 timestamp when the attempt started.
        end_time: ISO 8601 timestamp when the attempt ended (empty if running).
        status: Final status of the attempt (e.g., "success", "failed").
        exit_code: Process exit code, or None if not applicable.
        reason: Human-readable reason for this attempt (e.g., "manual resume").
    """

    sequence: int
    start_time: str = Field(default_factory=lambda: datetime.now().isoformat())
    end_time: str = ""
    status: str = "running"
    exit_code: int | None = None
    reason: str = ""


class Metadata(BaseModel):
    """Experiment metadata captured at initialization.

    Attributes:
        exp_id: Unique 16-character hexadecimal experiment identifier.
        timestamp: ISO 8601 timestamp when the experiment was created.
        git_hash: Git commit hash at initialization time (empty if not a repo).
        git_dirty: True if logic-critical files (src/, build config) have
            uncommitted changes. Documentation and test changes are ignored.
        tags: List of user-defined tags for categorization.
        data_version: Optional data version or hash for reproducibility.
        description: Human-readable description of the experiment.
        status: Current experiment status (default: "running").
        parent_id: ID of the parent experiment if this is an inherited run.
        attempts: List of execution attempts for resumption tracking.
    """

    exp_id: str
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    git_hash: str = ""
    git_dirty: bool = False
    tags: list[str] = Field(default_factory=list)
    data_version: str = ""
    description: str = ""
    status: str = "running"
    parent_id: str = ""
    attempts: list[Attempt] = Field(default_factory=list)
    group: str = "default"
    finished_at: str = ""
    locked: bool = False


class MetricsRow(BaseModel):
    """A single row of metrics logged during an experiment.

    Attributes:
        step: Training or evaluation step number.
        values: Dictionary mapping metric names to their numeric values.
        timestamp: Unix timestamp when the row was logged.
    """

    step: int
    values: dict[str, Any]
    timestamp: float = Field(default_factory=lambda: datetime.now().timestamp())
