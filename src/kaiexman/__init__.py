"""Kai-Exman: Rigorous Experiment Management.

This package provides a filesystem-based experiment management system
inspired by Git. It tracks metadata, metrics, artifacts, and environment
snapshots to ensure reproducible research and engineering workflows.

Key Components:
    ExMan: Manager class for creating, listing, and finishing experiments.
    Experiment: Instance class representing a single experiment directory.
    Metadata: Pydantic model for experiment metadata.
    MetricsRow: Pydantic model for a single metrics logging step.
"""

from kaiexman.experiment import Experiment
from kaiexman.manager import ExMan
from kaiexman.models import Metadata, MetricsRow

__all__ = ["ExMan", "Experiment", "Metadata", "MetricsRow"]
