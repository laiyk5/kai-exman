"""Experiment manager for Kai-Exman.

Provides the ExMan class, which serves as the primary entry point for
creating, listing, retrieving, and finishing experiments on the filesystem.
"""

import os
import uuid
from datetime import datetime
from pathlib import Path

from kaiexman.experiment import Experiment
from kaiexman.models import Metadata


class ExMan:
    """Manager for experiment lifecycle operations.

    All experiments are stored as subdirectories under a root path,
    following a structured layout with metadata, config, logs, and artifacts.

    Attributes:
        root: Resolved Path to the experiments root directory.
    """

    def __init__(self, root: str | None = None):
        """Initialize the experiment manager.

        Args:
            root: Path to the experiments directory. Defaults to
                the EXMAN_PATH environment variable or "./outputs".
        """
        self.root = Path(root or os.environ.get("EXMAN_PATH", "./outputs")).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _next_id(self) -> str:
        """Generate the next unique experiment identifier.

        Returns:
            An 8-character hexadecimal string derived from a UUID.
        """
        return uuid.uuid4().hex[:8]

    def _folder_name(self, date_str: str, exp_id: str, tags_or_desc: str) -> str:
        """Build a safe directory name for an experiment.

        Args:
            date_str: Date string in YYYYMMDD format.
            exp_id: Unique experiment identifier.
            tags_or_desc: Tags or description string to include in the name.

        Returns:
            A filesystem-safe directory name.
        """
        safe = "_".join(tags_or_desc.split())
        safe = "".join(c for c in safe if c.isalnum() or c in "_-").rstrip("_")
        return f"{date_str}_{exp_id}_{safe}" if safe else f"{date_str}_{exp_id}"

    def init(
        self,
        description: str = "",
        tags: list[str] | None = None,
        config: dict | None = None,
        data_version: str = "",
    ) -> Experiment:
        """Create and initialize a new experiment.

        Creates the experiment directory structure, writes metadata,
        config (if provided), and snapshots the Python environment.

        Args:
            description: Human-readable description of the experiment.
            tags: Optional list of categorical tags. Empty strings are filtered.
            config: Optional configuration dictionary to serialize as YAML.
            data_version: Optional data version identifier for reproducibility.

        Returns:
            The initialized Experiment instance.
        """
        date_str = datetime.now().strftime("%Y%m%d")
        exp_id = self._next_id()
        tags_or_desc = "_".join(tags) if tags else description
        folder = self.root / self._folder_name(date_str, exp_id, tags_or_desc)
        folder.mkdir(parents=True, exist_ok=True)

        (folder / "logs").mkdir(exist_ok=True)
        (folder / "artifacts" / "checkpoints").mkdir(parents=True, exist_ok=True)
        (folder / "artifacts" / "plots").mkdir(parents=True, exist_ok=True)

        tag_list = [t for t in (tags or []) if t]
        meta = Metadata(
            exp_id=exp_id,
            tags=tag_list,
            description=description,
            data_version=data_version,
        )
        exp = Experiment(root=folder, metadata=meta, config=config)
        exp.write_metadata()
        if config is not None:
            exp.write_config()
        exp.snapshot_env()
        return exp

    def finish(
        self,
        exp_id: str,
        status: str = "finished",
        notes: str = "",
    ) -> Experiment | None:
        """Finalize an experiment and generate its summary.

        Args:
            exp_id: Full experiment identifier.
            status: Final status string (default: "finished").
            notes: Optional post-mortem notes for the summary.

        Returns:
            The finished Experiment instance, or None if the ID was not found.
        """
        exp = self.get(exp_id)
        if exp is None:
            return None
        best_metrics = exp.compute_best_metrics()
        exp.write_summary(status=status, notes=notes, best_metrics=best_metrics)
        exp.update_status(status)
        return exp

    def list(self) -> list[Experiment]:
        """List all experiments under the root directory.

        Scans subdirectories for metadata.json files and reconstructs
        Experiment instances, restoring config from config.yaml when present.

        Returns:
            List of Experiment instances, ordered by filesystem discovery.
        """
        experiments: list[Experiment] = []
        for path in self.root.iterdir():
            if path.is_dir() and (path / "metadata.json").exists():
                meta = Metadata.model_validate_json(
                    (path / "metadata.json").read_text()
                )
                config = None
                config_path = path / "config.yaml"
                if config_path.exists():
                    import yaml

                    with config_path.open("r", encoding="utf-8") as f:
                        config = yaml.safe_load(f)
                experiments.append(Experiment(root=path, metadata=meta, config=config))
        return experiments

    def get(self, exp_id: str) -> Experiment | None:
        """Retrieve a single experiment by its full identifier.

        Args:
            exp_id: Full experiment identifier.

        Returns:
            The matching Experiment instance, or None if not found.
        """
        for exp in self.list():
            if exp.metadata.exp_id == exp_id:
                return exp
        return None
