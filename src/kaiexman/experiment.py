"""Experiment instance for Kai-Exman.

Provides the Experiment class, which represents a single experiment
directory and exposes methods for logging metrics, saving artifacts,
recording bad cases, and generating summaries.
"""

import json
import shutil
import subprocess
from pathlib import Path
from threading import Lock
from typing import Any

import yaml

from kaiexman.models import Metadata, MetricsRow


class Experiment:
    """A single experiment directory with associated metadata and operations.

    Attributes:
        root: Path to the experiment directory.
        metadata: Pydantic Metadata instance for this experiment.
        config: Configuration dictionary (may be empty).
    """

    def __init__(self, root: Path, metadata: Metadata, config: dict | None = None):
        """Initialize an Experiment instance.

        Args:
            root: Path to the experiment directory.
            metadata: Metadata model instance.
            config: Optional configuration dictionary.
        """
        self.root = root
        self.metadata = metadata
        self.config = config or {}
        self._metrics_path = root / "metrics.jsonl"
        self._bad_cases_path = root / "artifacts" / "bad_cases.json"
        self._lock = Lock()

    def _git_info(self) -> tuple[str, bool]:
        """Capture current Git repository state.

        Returns:
            Tuple of (commit hash, dirty flag). Returns ("", False) if
            Git is unavailable or the current directory is not a repository.
        """
        try:
            hash_raw = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
            dirty_raw = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                check=True,
            )
            return hash_raw.stdout.strip(), bool(dirty_raw.stdout.strip())
        except (subprocess.CalledProcessError, FileNotFoundError):
            return "", False

    def write_metadata(self) -> None:
        """Write metadata to metadata.json, capturing Git state."""
        git_hash, git_dirty = self._git_info()
        self.metadata.git_hash = git_hash
        self.metadata.git_dirty = git_dirty
        path = self.root / "metadata.json"
        path.write_text(self.metadata.model_dump_json(indent=2))

    def write_config(self) -> None:
        """Serialize the config dictionary to config.yaml."""
        path = self.root / "config.yaml"
        path.write_text(yaml.safe_dump(self.config, default_flow_style=False))

    def update_status(self, status: str) -> None:
        """Update the experiment status and rewrite metadata.

        Args:
            status: New status string (e.g., "finished", "failed").
        """
        self.metadata.status = status
        self.write_metadata()

    def log_metrics(self, step: int, values: dict) -> None:
        """Append a metrics row to metrics.jsonl in a thread-safe manner.

        NaN and infinite values are serialized as null by Pydantic v2.

        Args:
            step: Training or evaluation step number.
            values: Dictionary mapping metric names to numeric values.
        """
        row = MetricsRow(step=step, values=values)
        with self._lock:
            with self._metrics_path.open("a", encoding="utf-8") as f:
                f.write(row.model_dump_json() + "\n")

    def save_artifact(self, source_path: str, name: str | None = None) -> Path:
        """Copy a file or directory into the experiment artifacts folder.

        Args:
            source_path: Path to the source file or directory.
            name: Optional destination name. Defaults to the source basename.

        Returns:
            Path to the copied artifact within the experiment directory.

        Raises:
            FileNotFoundError: If the source path does not exist.
        """
        src = Path(source_path)
        dest_dir = self.root / "artifacts"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_name = name or src.name
        dest = dest_dir / dest_name
        if src.is_dir():
            shutil.copytree(src, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dest)
        return dest

    def log_bad_case(
        self,
        case_id: str,
        input_data: dict[str, Any],
        prediction: Any,
        ground_truth: Any,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Record a bad case for later analysis.

        Data is appended to artifacts/bad_cases.json. All values must be
        JSON-serializable.

        Args:
            case_id: Unique identifier for the case.
            input_data: Input features or data dictionary.
            prediction: Model prediction output.
            ground_truth: Ground truth or target value.
            extra: Optional additional metadata dictionary.

        Raises:
            TypeError: If the data contains non-JSON-serializable values.
        """
        entry = {
            "case_id": case_id,
            "input": input_data,
            "prediction": prediction,
            "ground_truth": ground_truth,
            "extra": extra or {},
        }
        with self._lock:
            cases: list[dict] = []
            if self._bad_cases_path.exists():
                cases = json.loads(self._bad_cases_path.read_text(encoding="utf-8"))
            cases.append(entry)
            self._bad_cases_path.parent.mkdir(parents=True, exist_ok=True)
            self._bad_cases_path.write_text(
                json.dumps(cases, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    def snapshot_env(self) -> None:
        """Snapshot the current Python environment to env.txt.

        Captures the output of ``pip list --format=freeze``. If pip is
        unavailable, writes a placeholder comment instead.
        """
        env_path = self.root / "env.txt"
        try:
            result = subprocess.run(
                ["pip", "list", "--format=freeze"],
                capture_output=True,
                text=True,
                check=True,
            )
            env_path.write_text(result.stdout, encoding="utf-8")
        except (subprocess.CalledProcessError, FileNotFoundError):
            env_path.write_text("# pip not available\n", encoding="utf-8")

    def compute_best_metrics(self) -> dict[str, dict[str, float]]:
        """Compute the best (max and min) value for each metric.

        Skips corrupted or blank lines in metrics.jsonl gracefully.
        Non-numeric and null values are ignored.

        Returns:
            Dictionary mapping metric names to {"max": float, "min": float}.
            Returns an empty dict if no metrics file exists or no valid entries.
        """
        if not self._metrics_path.exists():
            return {}
        best: dict[str, dict[str, float]] = {}
        with self._metrics_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for key, value in row.get("values", {}).items():
                    if not isinstance(value, (int, float)):
                        continue
                    if key not in best:
                        best[key] = {"max": value, "min": value}
                    else:
                        best[key]["max"] = max(best[key]["max"], value)
                        best[key]["min"] = min(best[key]["min"], value)
        return best

    def write_summary(
        self,
        status: str = "finished",
        notes: str = "",
        best_metrics: dict[str, dict[str, float]] | None = None,
    ) -> None:
        """Generate a Markdown summary report in the experiment directory.

        Args:
            status: Final experiment status.
            notes: Post-mortem or analysis notes.
            best_metrics: Optional pre-computed best metrics dictionary.
        """
        summary_path = self.root / "summary.md"
        meta = self.metadata
        metrics_block = ""
        if best_metrics:
            metrics_block = "| Metric | Best (Max) | Worst (Min) |\n"
            metrics_block += "|--------|-----------|------------|\n"
            for key, vals in best_metrics.items():
                metrics_block += f"| {key} | {vals['max']:.6f} | {vals['min']:.6f} |\n"
        else:
            metrics_block = "_No metrics recorded._\n"

        content = f"""# Experiment Summary

## Metadata
- **ID**: {meta.exp_id}
- **Status**: {status}
- **Git Hash**: {meta.git_hash or "N/A"}
- **Git Dirty**: {meta.git_dirty}
- **Data Version**: {meta.data_version or "N/A"}
- **Description**: {meta.description or "N/A"}

## Best Metrics
{metrics_block}

## Notes
{notes or "_No notes provided._"}

## Next Steps
<!-- TODO: Fill in your insights and next actions -->
"""
        summary_path.write_text(content, encoding="utf-8")
