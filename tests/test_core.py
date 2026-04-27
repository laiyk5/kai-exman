import json
import sys
from pathlib import Path

src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src))

from kaiexman import ExMan


def test_experiment_init(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(
        description="pytest init test",
        tags=["pytest", "init"],
        config={"lr": 0.001},
        data_version="md5:cafebabe",
    )

    assert exp.metadata.exp_id != ""
    assert exp.metadata.data_version == "md5:cafebabe"
    assert exp.metadata.status == "running"
    assert exp.root.exists()
    assert (exp.root / "metadata.json").exists()
    assert (exp.root / "config.yaml").exists()
    assert (exp.root / "env.txt").exists()


def test_metrics_logging(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="metrics test")

    exp.log_metrics(0, {"loss": 1.2, "acc": 0.5})
    exp.log_metrics(1, {"loss": 0.8, "acc": 0.72})
    exp.log_metrics(2, {"loss": 0.6, "acc": 0.85})

    metrics_file = exp.root / "metrics.jsonl"
    assert metrics_file.exists()

    lines = metrics_file.read_text().strip().split("\n")
    assert len(lines) == 3

    row0 = json.loads(lines[0])
    assert row0["step"] == 0
    assert row0["values"]["loss"] == 1.2

    row2 = json.loads(lines[2])
    assert row2["step"] == 2
    assert row2["values"]["acc"] == 0.85


def test_bad_case_logging(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="bad case test")

    exp.log_bad_case(
        case_id="case_a",
        input_data={"text": "hello"},
        prediction="positive",
        ground_truth="negative",
        extra={"confidence": 0.9},
    )
    exp.log_bad_case(
        case_id="case_b",
        input_data={"text": "world"},
        prediction="neutral",
        ground_truth="positive",
    )

    bad_cases_file = exp.root / "artifacts" / "bad_cases.json"
    assert bad_cases_file.exists()

    cases = json.loads(bad_cases_file.read_text())
    assert len(cases) == 2
    assert cases[0]["case_id"] == "case_a"
    assert cases[1]["ground_truth"] == "positive"


def test_artifact_saving(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="artifact test")

    dummy_src = exp.root / "artifacts" / "dummy.txt"
    dummy_src.write_text("hello artifact")
    dest = exp.save_artifact(str(dummy_src), name="copied_dummy.txt")

    assert dest.exists()
    assert dest.read_text() == "hello artifact"
    assert dest.name == "copied_dummy.txt"


def test_experiment_finish(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="finish test")

    exp.log_metrics(0, {"loss": 1.0, "acc": 0.5})
    exp.log_metrics(1, {"loss": 0.5, "acc": 0.9})

    # finish() requires at least one attempt with an exit_code
    from kaiexman.models import Attempt

    exp.metadata.attempts.append(
        Attempt(sequence=1, status="running", exit_code=0)
    )
    exp.write_metadata()

    finished = exman.finish(
        exp_id=exp.metadata.exp_id,
        notes="Looks good.",
    )

    assert finished.metadata.status == "success"

    summary_file = finished.root / "summary.md"
    assert summary_file.exists()

    summary_text = summary_file.read_text()
    assert "Looks good." in summary_text
    assert "acc" in summary_text


def test_list_and_get(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp1 = exman.init(description="exp one", tags=["a"])
    _ = exman.init(description="exp two", tags=["b"])

    all_exps = exman.list()
    assert len(all_exps) == 2

    retrieved = exman.get(exp1.metadata.exp_id)
    assert retrieved is not None
    assert retrieved.metadata.exp_id == exp1.metadata.exp_id
    assert retrieved.metadata.description == "exp one"

    missing = exman.get("nonexistent")
    assert missing is None


def test_init_truncates_long_description_in_folder_name(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    long_desc = "A" * 200
    exp = exman.init(description=long_desc)
    # The folder name should be truncated to avoid overly long paths
    name_part = exp.root.name
    desc_part = name_part.split("_")[-1]
    assert len(desc_part) <= 50
    assert desc_part == "A" * 50
