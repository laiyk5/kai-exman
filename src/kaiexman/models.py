from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Metadata(BaseModel):
    exp_id: str
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    git_hash: str = ""
    git_dirty: bool = False
    tags: list[str] = Field(default_factory=list)
    data_version: str = ""
    description: str = ""
    status: str = "running"


class MetricsRow(BaseModel):
    step: int
    values: dict[str, Any]
    timestamp: float = Field(default_factory=lambda: datetime.now().timestamp())
