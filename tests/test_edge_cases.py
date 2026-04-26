import json
import sys
from pathlib import Path

src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src))

import pytest

from kaiexman import ExMan

# Bug 1: save_artifact with missing source


def test_save_artifact_missing_source_graceful(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="artifact missing")
    with pytest.raises(FileNotFoundError):
        exp.save_artifact("/nonexistent/file.txt")


# Bug 2: compute_best_metrics with corrupted JSONL


def test_compute_best_metrics_skips_corrupted_lines(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="corrupted metrics")
    metrics_file = exp.root / "metrics.jsonl"
    metrics_file.write_text(
        '{"step":0,"values":{"loss":1.0}}\n'
        "{invalid json}\n"
        '{"step":1,"values":{"loss":0.5}}\n'
    )

    best = exp.compute_best_metrics()
    assert best == {"loss": {"max": 1.0, "min": 0.5}}


# -- Bug 3: log_bad_case with non-serializable data -----------------------


def test_log_bad_case_non_serializable_fails_cleanly(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="bad case serializable")
    with pytest.raises(TypeError):
        exp.log_bad_case("case1", {"data": {1, 2, 3}}, "pred", "gt")


# -- Bug 4: config not loaded on get/list ----------------------------------


def test_get_restores_config(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    original = exman.init(description="with config", config={"lr": 0.01, "epochs": 10})
    retrieved = exman.get(original.metadata.exp_id)
    assert retrieved.config == {"lr": 0.01, "epochs": 10}


def test_list_restores_config(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exman.init(description="cfg1", config={"lr": 0.01})
    exman.init(description="cfg2", config={"lr": 0.001})

    experiments = exman.list()
    assert len(experiments) == 2
    configs = [e.config for e in experiments]
    assert {"lr": 0.01} in configs
    assert {"lr": 0.001} in configs


# -- Edge: empty metrics file ----------------------------------------------


def test_compute_best_metrics_empty_file(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="no metrics")
    assert exp.compute_best_metrics() == {}


# -- Edge: log_metrics with NaN / inf --------------------------------------


def test_log_metrics_nan_inf_becomes_null(tmp_exman_path):
    """Pydantic v2 serializes NaN/inf as null; they are skipped in best metrics."""
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="nan inf")
    exp.log_metrics(0, {"loss": float("nan"), "acc": float("inf")})

    lines = (exp.root / "metrics.jsonl").read_text().strip().split("\n")
    row = json.loads(lines[0])
    assert row["values"]["loss"] is None
    assert row["values"]["acc"] is None

    best = exp.compute_best_metrics()
    assert best == {}


# -- Edge: description with special chars ----------------------------------


def test_init_sanitizes_description_for_folder_name(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="path/with\\slashes and spaces!")
    assert "/" not in exp.root.name
    assert "\\" not in exp.root.name
    assert "!" not in exp.root.name


# -- Edge: whitespace-only lines in metrics.jsonl --------------------------


def test_compute_best_metrics_skips_blank_lines(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="blank lines")
    metrics_file = exp.root / "metrics.jsonl"
    metrics_file.write_text(
        '\n{"step":0,"values":{"acc":0.9}}\n\n{"step":1,"values":{"acc":0.95}}\n\n'
    )

    best = exp.compute_best_metrics()
    assert best == {"acc": {"max": 0.95, "min": 0.9}}


# -- Edge: finish on non-existent experiment -------------------------------


def test_finish_nonexistent_experiment_returns_none(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    result = exman.finish(exp_id="does_not_exist", status="success")
    assert result is None


# -- Edge: tags with empty entries -----------------------------------------


def test_init_tags_with_empty_entries(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="tags test", tags=["", "valid", "", "also_valid", ""])
    assert "valid" in exp.metadata.tags
    assert "" not in exp.metadata.tags
