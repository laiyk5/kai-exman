"""Experiment manager for Kai-Exman.

Provides the ExMan class, which serves as the primary entry point for
creating, listing, retrieving, and finishing experiments on the filesystem.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, List, Tuple

from kaiexman.config import ConfigManager
from kaiexman.experiment import Experiment, validate_group, validate_tag
from kaiexman.models import Attempt, Metadata


class ExMan:
    """Manager for experiment lifecycle operations.

    All experiments are stored as subdirectories under a root path,
    following a grouped layout: root/group/date_id_desc/.

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
        self._ensure_layout()

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

    # ------------------------------------------------------------------
    # Layout & backward compatibility
    # ------------------------------------------------------------------

    def _ensure_layout(self) -> None:
        """Migrate flat v0.1.0 layout to grouped v0.2.0 layout if needed."""
        default_group = self.root / "default"
        if default_group.exists():
            return

        # Detect old-style flat directories directly under root
        old_experiments: List[Path] = []
        for path in self.root.iterdir():
            if path.name == ".trash" or not path.is_dir():
                continue
            if (path / "metadata.json").exists():
                old_experiments.append(path)

        if not old_experiments:
            return

        default_group.mkdir(parents=True, exist_ok=True)
        for exp_path in old_experiments:
            dest = default_group / exp_path.name
            shutil.move(str(exp_path), str(dest))

        # Rewrite metadata.group for migrated experiments
        for exp_path in old_experiments:
            meta_path = default_group / exp_path.name / "metadata.json"
            if meta_path.exists():
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                data["group"] = "default"
                meta_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        self.rebuild_index()
        print(
            "[kai-exman] Migrated existing experiments to group 'default'. "
            "See docs/source/design/organization.md for details."
        )

    # ------------------------------------------------------------------
    # Index cache
    # ------------------------------------------------------------------

    def _index_path(self) -> Path:
        """Return the path to the index cache file."""
        return self.root / "index.json"

    def _load_index(self) -> dict[str, Any] | None:
        """Load the index cache if it exists and is valid.

        Returns:
            Parsed index dict, or None if missing or invalid.
        """
        path = self._index_path()
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("version") != 1:
                return None
            return data  # type: ignore[no-any-return]
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def _save_index(self, data: dict[str, Any]) -> None:
        """Write the index cache atomically.

        Args:
            data: Index dictionary to persist.
        """
        path = self._index_path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(path))

    def rebuild_index(self) -> dict[str, Any]:
        """Rebuild the index cache by scanning all groups.

        Returns:
            The rebuilt index dictionary.
        """
        index: dict[str, Any] = {
            "version": 1,
            "last_rebuilt": datetime.now().isoformat(),
            "experiments": {},
            "tag_index": {},
            "group_index": {},
        }
        for exp in self._scan_all():
            meta = exp.metadata
            rel_path = str(exp.root.relative_to(self.root))
            index["experiments"][meta.exp_id] = {
                "rel_path": rel_path,
                "group": meta.group,
                "parent_id": meta.parent_id,
                "tags": list(meta.tags),
            }
            for tag in meta.tags:
                index["tag_index"].setdefault(tag, []).append(meta.exp_id)
            index["group_index"].setdefault(meta.group, []).append(meta.exp_id)

        self._save_index(index)
        return index

    def _update_index(
        self,
        exp: Experiment,
        operation: str,
    ) -> None:
        """Update the index cache after a mutating operation.

        Args:
            exp: The experiment that was created, moved, or removed.
            operation: One of "add", "move", "remove".
        """
        index = self._load_index()
        if index is None:
            index = self.rebuild_index()
            return

        meta = exp.metadata
        exp_id = meta.exp_id

        if operation == "remove":
            index["experiments"].pop(exp_id, None)
            for tag_list in index["tag_index"].values():
                if exp_id in tag_list:
                    tag_list.remove(exp_id)
            for group_list in index["group_index"].values():
                if exp_id in group_list:
                    group_list.remove(exp_id)
            self._save_index(index)
            return

        # For add or move, update / insert the entry
        rel_path = str(exp.root.relative_to(self.root))
        old_entry = index["experiments"].get(exp_id)

        # Clean up old tag and group references if the entry exists
        if old_entry is not None:
            old_tags = old_entry.get("tags", [])
            old_group = old_entry.get("group", "default")
            for tag in old_tags:
                if tag in index["tag_index"] and exp_id in index["tag_index"][tag]:
                    index["tag_index"][tag].remove(exp_id)
            group_idx = index["group_index"]
            if old_group in group_idx and exp_id in group_idx[old_group]:
                group_idx[old_group].remove(exp_id)

        index["experiments"][exp_id] = {
            "rel_path": rel_path,
            "group": meta.group,
            "parent_id": meta.parent_id,
            "tags": list(meta.tags),
        }
        for tag in meta.tags:
            index["tag_index"].setdefault(tag, [])
            if exp_id not in index["tag_index"][tag]:
                index["tag_index"][tag].append(exp_id)
        index["group_index"].setdefault(meta.group, [])
        if exp_id not in index["group_index"][meta.group]:
            index["group_index"][meta.group].append(exp_id)

        self._save_index(index)

    # ------------------------------------------------------------------
    # Low-level scanning
    # ------------------------------------------------------------------

    def _scan_group(self, group_path: Path) -> List[Experiment]:
        """Scan a single group directory for experiments.

        Args:
            group_path: Path to the group directory.

        Returns:
            List of Experiment instances found in the group.
        """
        experiments: List[Experiment] = []
        if not group_path.exists():
            return experiments
        for path in group_path.iterdir():
            if not path.is_dir():
                continue
            meta_path = path / "metadata.json"
            if not meta_path.exists():
                continue
            try:
                meta = Metadata.model_validate_json(
                    meta_path.read_text(encoding="utf-8")
                )
            except Exception:
                continue
            config = None
            config_path = path / "config.yaml"
            if config_path.exists():
                import yaml

                with config_path.open("r", encoding="utf-8") as f:
                    config = yaml.safe_load(f)
            experiments.append(
                Experiment(root=path, metadata=meta, config=config)
            )
        return experiments

    def _scan_all(self) -> List[Experiment]:
        """Scan all groups for experiments.

        Returns:
            List of all Experiment instances.
        """
        experiments: List[Experiment] = []
        for path in self.root.iterdir():
            if path.name == ".trash" or not path.is_dir():
                continue
            experiments.extend(self._scan_group(path))
        return experiments

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def init(
        self,
        description: str = "",
        tags: List[str] | None = None,
        config: dict[str, Any] | None = None,
        data_version: str = "",
        group: str = "default",
    ) -> Experiment:
        """Create and initialize a new experiment.

        Creates the experiment directory structure under the specified group,
        writes metadata, config (if provided), and snapshots the environment.

        Args:
            description: Human-readable description of the experiment.
            tags: Optional list of categorical tags. Empty strings are filtered.
            config: Optional configuration dictionary to serialize as YAML.
            data_version: Optional data version identifier for reproducibility.
            group: Group name for physical organization (default: "default").

        Returns:
            The initialized Experiment instance.
        """
        validate_group(group)
        date_str = datetime.now().strftime("%Y%m%d")
        exp_id = self._next_id()
        tags_or_desc = "_".join(tags) if tags else description
        group_dir = self.root / group
        group_dir.mkdir(parents=True, exist_ok=True)
        folder = group_dir / self._folder_name(date_str, exp_id, tags_or_desc)
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
            group=group,
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
        self._update_index(exp, "add")
        return exp

    def finish(
        self,
        exp_id: str,
        status: str = "finished",
        notes: str = "",
    ) -> Experiment | None:
        """Finalize an experiment and generate its summary.

        If the experiment has attempt history, the last attempt's status is
        also updated to match the final status, ensuring the global status
        and attempt history remain consistent.

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
        if exp.metadata.attempts:
            last = exp.metadata.attempts[-1]
            last.status = status
            if not last.end_time:
                last.end_time = datetime.now().isoformat()
        exp.update_status(status)
        self._update_index(exp, "add")
        return exp

    def list(self, group: str | None = None) -> List[Experiment]:
        """List all experiments under the root directory.

        Scans group subdirectories for metadata.json files and reconstructs
        Experiment instances. The ``.trash/`` directory is excluded.

        Args:
            group: Optional group name to filter by. If provided, only
                experiments in that group are returned.

        Returns:
            List of Experiment instances, ordered by filesystem discovery.
        """
        if group is not None:
            return self._scan_group(self.root / group)

        experiments: List[Experiment] = []
        for path in self.root.iterdir():
            if path.name == ".trash" or not path.is_dir():
                continue
            experiments.extend(self._scan_group(path))
        return experiments

    def get(self, exp_id: str) -> Experiment | None:
        """Retrieve a single experiment by its full identifier.

        Uses the index cache for O(1) lookup when available; falls back
        to a full filesystem scan if the index is missing or stale.

        Args:
            exp_id: Full experiment identifier.

        Returns:
            The matching Experiment instance, or None if not found.
        """
        index = self._load_index()
        if index and exp_id in index["experiments"]:
            rel_path = index["experiments"][exp_id]["rel_path"]
            path = self.root / rel_path
            if path.exists() and (path / "metadata.json").exists():
                try:
                    meta = Metadata.model_validate_json(
                        (path / "metadata.json").read_text(encoding="utf-8")
                    )
                except Exception:
                    pass
                else:
                    config = None
                    config_path = path / "config.yaml"
                    if config_path.exists():
                        import yaml

                        with config_path.open("r", encoding="utf-8") as f:
                            config = yaml.safe_load(f)
                    return Experiment(root=path, metadata=meta, config=config)
            # Stale index entry — rebuild and fall through
            index = self.rebuild_index()

        # Fallback: full scan
        for exp in self.list():
            if exp.metadata.exp_id == exp_id:
                return exp
        return None

    def _current_git_state(self) -> Tuple[str, bool]:
        """Capture the current Git repository state.

        Returns:
            Tuple of (commit hash, dirty flag).
        """
        return Experiment._git_info(
            critical_paths=self.config.get("critical_paths")
        )

    def resume(
        self,
        exp_id: str,
        description: str = "",
        tags: List[str] | None = None,
        config: dict[str, Any] | None = None,
        data_version: str = "",
        group: str | None = None,
    ) -> Tuple[Experiment, bool, int]:
        """Resume an experiment with context-aware logic.

        Case A (Logic-Clean): If the current workspace matches the parent's
        Git commit and is clean, the existing experiment is reopened and a
        new attempt is appended.

        Case B (Logic-Dirty): If the workspace has diverged, a new experiment
        is created with ``parent_id`` set and checkpoints/configs are copied
        from the parent.

        Args:
            exp_id: Full ID of the experiment to resume from.
            description: Description for a new experiment (Case B).
            tags: Tags for a new experiment (Case B, defaults to parent's).
            config: Config for a new experiment (Case B, defaults to parent's).
            data_version: Data version for a new experiment (Case B).
            group: Group for a new experiment (Case B). Ignored for Case A.

        Returns:
            Tuple of (experiment, is_new_experiment, attempt_number).

        Raises:
            ValueError: If the parent experiment is not found.
        """
        parent = self.get(exp_id)
        if parent is None:
            raise ValueError(f"Experiment '{exp_id}' not found")

        current_hash, current_dirty = self._current_git_state()

        # Case A: Logic-Clean Resume (Retry)
        if (
            current_hash
            and current_hash == parent.metadata.git_hash
            and not current_dirty
        ):
            if group is not None and group != parent.metadata.group:
                warnings.warn(
                    f"--group ignored for Case A resume; experiment remains "
                    f"in '{parent.metadata.group}'.",
                    stacklevel=2,
                )
            attempt_num = len(parent.metadata.attempts) + 1
            new_attempt = Attempt(
                sequence=attempt_num,
                status="running",
                reason=f"run_{attempt_num}",
            )
            parent.metadata.attempts.append(new_attempt)
            parent.metadata.status = "running"
            parent.write_metadata()
            self._update_index(parent, "add")
            return parent, False, attempt_num

        # Case B: Logic-Dirty Resume (Evolution)
        child = self.init(
            description=description or f"inherited from {parent.metadata.exp_id}",
            tags=tags if tags is not None else list(parent.metadata.tags),
            config=config if config is not None else dict(parent.config),
            data_version=data_version,
            group=group or "default",
        )
        child.metadata.parent_id = parent.metadata.exp_id
        child.write_metadata()
        self._update_index(child, "add")

        # Symlink checkpoints from parent (fallback to hard copy)
        parent_ckpt = parent.root / "artifacts" / "checkpoints"
        child_ckpt = child.root / "artifacts" / "checkpoints"
        if parent_ckpt.exists():
            for src in parent_ckpt.iterdir():
                dest = child_ckpt / src.name
                try:
                    os.symlink(src.resolve(), dest)
                except OSError:
                    warnings.warn(
                        f"Symlink failed for {src.name}, falling back to copy. "
                        "Enable Developer Mode on Windows for symlink support.",
                        stacklevel=2,
                    )
                    if src.is_dir():
                        shutil.copytree(src, dest, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, dest)

        return child, True, 1

    def move(self, exp_id: str, new_group: str) -> Experiment:
        """Move an experiment to a different group.

        Physically moves the experiment directory, updates metadata.group,
        and syncs the index cache.

        Args:
            exp_id: Full experiment identifier.
            new_group: Target group name.

        Returns:
            The moved Experiment instance.

        Raises:
            ValueError: If the experiment is not found.
        """
        validate_group(new_group)
        exp = self.get(exp_id)
        if exp is None:
            raise ValueError(f"Experiment '{exp_id}' not found")

        if exp.metadata.group == new_group:
            return exp

        new_group_dir = self.root / new_group
        new_group_dir.mkdir(parents=True, exist_ok=True)
        dest = new_group_dir / exp.root.name
        shutil.move(str(exp.root), str(dest))

        exp.root = dest
        exp.metadata.group = new_group
        exp.write_metadata()
        self._update_index(exp, "move")
        return exp

    def suggest_groups(self) -> List[Tuple[Experiment, str, float]]:
        """Suggest group assignments based on config key similarity.

        Computes Jaccard similarity between each experiment's config keys
        and those of all other experiments. Returns suggestions where the
        similarity meets the configured threshold.

        Returns:
            List of (experiment, suggested_group, similarity_score) tuples.
        """
        threshold = self.config.get("cluster_threshold", 0.5)
        all_experiments = self.list()
        suggestions: List[Tuple[Experiment, str, float]] = []

        for exp in all_experiments:
            target_keys = set(exp.config.keys())
            if not target_keys:
                continue
            best_group = None
            best_score = 0.0
            for other in all_experiments:
                if other.metadata.exp_id == exp.metadata.exp_id:
                    continue
                other_keys = set(other.config.keys())
                if not other_keys:
                    continue
                intersection = len(target_keys & other_keys)
                union = len(target_keys | other_keys)
                score = intersection / union if union else 0.0
                if score > best_score:
                    best_score = score
                    best_group = other.metadata.group
            if best_group is not None and best_score >= threshold:
                suggestions.append((exp, best_group, best_score))

        return suggestions

    # ------------------------------------------------------------------
    # Trash
    # ------------------------------------------------------------------

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
        items: List[Tuple[Path, datetime]] = []
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

        purged: List[Path] = []

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
            self._update_index(exp, "remove")

        return exp, purged

    def clear_trash(self, dry_run: bool = False) -> List[Path]:
        """Permanently delete all items in the trash.

        Args:
            dry_run: If True, only record what would be deleted.

        Returns:
            List of paths that were (or would be) permanently deleted.
        """
        items = self._trash_items()
        deleted: List[Path] = []
        for path, _ in items:
            deleted.append(path)
            if not dry_run:
                shutil.rmtree(path)
        return deleted
