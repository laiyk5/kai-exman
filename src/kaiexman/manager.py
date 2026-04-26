import os
import uuid
from datetime import datetime
from pathlib import Path

from kaiexman.experiment import Experiment
from kaiexman.models import Metadata


class ExMan:
    def __init__(self, root: str | None = None):
        self.root = Path(root or os.environ.get("EXMAN_PATH", "./outputs")).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _next_id(self) -> str:
        return uuid.uuid4().hex[:8]

    def _folder_name(self, date_str: str, exp_id: str, tags_or_desc: str) -> str:
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
        exp = self.get(exp_id)
        if exp is None:
            return None
        best_metrics = exp.compute_best_metrics()
        exp.write_summary(status=status, notes=notes, best_metrics=best_metrics)
        exp.update_status(status)
        return exp

    def list(self) -> list[Experiment]:
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
        for exp in self.list():
            if exp.metadata.exp_id == exp_id:
                return exp
        return None
