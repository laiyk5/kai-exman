"""Experiment manager for Kai-Exman.

Provides the ExMan class, which serves as the primary entry point for
creating, listing, retrieving, and finishing experiments on the filesystem.
"""

import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, List, Tuple

from kaiexman.config import ConfigManager
from kaiexman.experiment import Experiment, validate_tag
from kaiexman.models import Metadata


class ExMan:
    """Manager for experiment lifecycle operations.

    All experiments are stored as subdirectories under a root path,
    following a structured layout with metadata, config, logs, and artifacts.

    Attributes:
        root: Resolved Path to the experiments root directory.
        config: ConfigManager instance holding merged settings.
    """

    def __init__(
        self,
        root: str | None = None,
        config: ConfigManager | None = None,
    ):
        """Initialize the experiment manager.

        Args:
            root: Path to the experiments directory. Defaults to
                the EXMAN_PATH environment variable or "./outputs".
            config: Optional ConfigManager. A new one is created with
                defaults if not provided.
        """
        self.root = Path(root or os.environ.get("EXMAN_PATH", "./outputs")).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.config = config if config is not None else ConfigManager()

    def _next_id(self) -> str:
        """Generate the next unique experiment identifier.

        Returns:
            A 16-character hexadecimal string derived from a UUID.
        """
        return uuid.uuid4().hex[:16]

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
        safe = "".join(
            c for c in safe if (c.isascii() and c.isalnum()) or c in "_-"
        ).rstrip("_")
        return f"{date_str}_{exp_id}_{safe}" if safe else f"{date_str}_{exp_id}"

    def init(
        self,
        description: str = "",
        tags: list[str] | None = None,
        config: dict[str, Any] | None = None,
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

        tag_list = tags or []
        for tag in tag_list:
            validate_tag(tag)
        meta = Metadata(
            exp_id=exp_id,
            tags=tag_list,
            description=description,
            data_version=data_version,
        )
        exp = Experiment(
            root=folder,
            metadata=meta,
            config=config,
            critical_paths=self.config.get("critical_paths"),
        )
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

    def list(self) -> List[Experiment]:
        """List all experiments under the root directory.

        Scans subdirectories for metadata.json files and reconstructs
        Experiment instances, restoring config from config.yaml when present.
        The ``.trash/`` directory is excluded from discovery.

        Returns:
            List of Experiment instances, ordered by filesystem discovery.
        """
        experiments: list[Experiment] = []
        for path in self.root.iterdir():
            if path.name == ".trash" or not path.is_dir():
                continue
            if (path / "metadata.json").exists():
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

    def _trash_dir(self) -> Path:
        """Return the path to the trash directory, creating it if needed.

        Returns:
            Path to the ``.trash/`` subdirectory under the root.
        """
        trash = self.root / ".trash"
        trash.mkdir(parents=True, exist_ok=True)
        return trash

    @staticmethod
    def _dir_size_bytes(path: Path) -> int:
        """Calculate the total size of a directory or file in bytes.

        Args:
            path: Path to a file or directory.

        Returns:
            Total size in bytes.
        """
        total = 0
        if path.is_file():
            return path.stat().st_size
        for item in path.rglob("*"):
            if item.is_file():
                total += item.stat().st_size
        return total

    def _trash_items(self) -> List[Tuple[Path, datetime]]:
        """List all trashed experiment folders with deletion timestamps.

        Reads ``.deletion_info`` files for accurate timestamps; falls back
        to filesystem mtime when metadata is missing or corrupt.

        Returns:
            List of (path, deleted_at) tuples sorted oldest first.
        """
        trash = self._trash_dir()
        items: list[tuple[Path, datetime]] = []
        for item in trash.iterdir():
            if not item.is_dir():
                continue
            info_path = item / ".deletion_info"
            deleted_at = datetime.fromtimestamp(item.stat().st_mtime)
            if info_path.exists():
                try:
                    data = json.loads(info_path.read_text(encoding="utf-8"))
                    deleted_at = datetime.fromisoformat(data["deleted_at"])
                except (KeyError, ValueError, json.JSONDecodeError):
                    pass
            items.append((item, deleted_at))
        items.sort(key=lambda x: x[1])
        return items

    def _ensure_trash_capacity(
        self,
        dry_run: bool = False,
        pending_count: int = 0,
        pending_size: int = 0,
    ) -> List[Path]:
        """Purge oldest trashed experiments until capacity limits are met.

        Accounts for items that are about to be added to trash.

        Args:
            dry_run: If True, only record what would be deleted.
            pending_count: Number of items about to enter trash.
            pending_size: Total size in bytes of items about to enter trash.

        Returns:
            List of paths that were (or would be) permanently deleted.
        """
        max_count = self.config.get("trash_max_count", 50)
        max_size_gb = self.config.get("trash_max_size_gb", 5.0)
        max_size_bytes = int(max_size_gb * 1024 * 1024 * 1024)

        items = self._trash_items()
        total_count = len(items) + pending_count
        total_size = sum(self._dir_size_bytes(p) for p, _ in items) + pending_size

        purged: list[Path] = []

        while items and (total_count > max_count or total_size > max_size_bytes):
            oldest_path, _ = items.pop(0)
            size = self._dir_size_bytes(oldest_path)
            purged.append(oldest_path)
            if not dry_run:
                shutil.rmtree(oldest_path)
            total_count -= 1
            total_size -= size

        return purged

    def remove(
        self, exp_id: str, dry_run: bool = False
    ) -> Tuple[Experiment | None, List[Path]]:
        """Move an experiment to the trash directory.

        Before moving, ensures the trash has capacity by purging the oldest
        items if necessary. Writes a ``.deletion_info`` file inside the
        trashed folder to track the deletion timestamp.

        Args:
            exp_id: Full experiment identifier.
            dry_run: If True, only report what would happen.

        Returns:
            Tuple of (experiment, list of purged paths). The experiment is
            None if the ID was not found.
        """
        exp = self.get(exp_id)
        if exp is None:
            return None, []

        pending_size = self._dir_size_bytes(exp.root)
        purged = self._ensure_trash_capacity(
            dry_run=dry_run, pending_count=1, pending_size=pending_size
        )

        if not dry_run:
            trash = self._trash_dir()
            dest = trash / exp.root.name

            deletion_info = {
                "deleted_at": datetime.now().isoformat(),
                "original_path": str(exp.root),
            }
            info_path = exp.root / ".deletion_info"
            info_path.write_text(json.dumps(deletion_info, indent=2), encoding="utf-8")
            shutil.move(str(exp.root), str(dest))

        return exp, purged

    def clear_trash(self, dry_run: bool = False) -> List[Path]:
        """Permanently delete all items in the trash.

        Args:
            dry_run: If True, only record what would be deleted.

        Returns:
            List of paths that were (or would be) permanently deleted.
        """
        items = self._trash_items()
        deleted: list[Path] = []
        for path, _ in items:
            deleted.append(path)
            if not dry_run:
                shutil.rmtree(path)
        return deleted
