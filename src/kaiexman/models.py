"""Pydantic models for Kai-Exman experiment data.

Defines the core data structures used for experiment metadata and
metrics logging, enforcing validation and serialization through
Pydantic v2.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Metadata(BaseModel):
    """Experiment metadata captured at initialization.

    Attributes:
        exp_id: Unique 8-character hexadecimal experiment identifier.
        timestamp: ISO 8601 timestamp when the experiment was created.
        git_hash: Git commit hash at initialization time (empty if not a repo).
        git_dirty: Whether the working tree had uncommitted changes.
        tags: List of user-defined tags for categorization.
        data_version: Optional data version or hash for reproducibility.
        description: Human-readable description of the experiment.
        status: Current experiment status (default: "running").
    """

    exp_id: str
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    git_hash: str = ""
    git_dirty: bool = False
    tags: list[str] = Field(default_factory=list)
    data_version: str = ""
    description: str = ""
    status: str = "running"


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
