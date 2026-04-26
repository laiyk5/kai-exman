import json
import shutil
import subprocess
from pathlib import Path
from threading import Lock
from typing import Any

import yaml

from kaiexman.models import Metadata, MetricsRow


class Experiment:
    def __init__(self, root: Path, metadata: Metadata, config: dict | None = None):
        self.root = root
        self.metadata = metadata
        self.config = config or {}
        self._metrics_path = root / "metrics.jsonl"
        self._bad_cases_path = root / "artifacts" / "bad_cases.json"
        self._lock = Lock()

    def _git_info(self) -> tuple[str, bool]:
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
        git_hash, git_dirty = self._git_info()
        self.metadata.git_hash = git_hash
        self.metadata.git_dirty = git_dirty
        path = self.root / "metadata.json"
        path.write_text(self.metadata.model_dump_json(indent=2))

    def write_config(self) -> None:
        path = self.root / "config.yaml"
        path.write_text(yaml.safe_dump(self.config, default_flow_style=False))

    def update_status(self, status: str) -> None:
        self.metadata.status = status
        self.write_metadata()

    def log_metrics(self, step: int, values: dict) -> None:
        row = MetricsRow(step=step, values=values)
        with self._lock:
            with self._metrics_path.open("a", encoding="utf-8") as f:
                f.write(row.model_dump_json() + "\n")

    def save_artifact(self, source_path: str, name: str | None = None) -> Path:
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
