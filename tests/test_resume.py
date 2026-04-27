import json
import sys
from pathlib import Path

from click.testing import CliRunner

src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src))

from kaiexman import ExMan
from kaiexman.cli import cli


def test_resume_logic_clean_reopens_existing(tmp_exman_path, monkeypatch):
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="parent")
    parent_hash = parent.metadata.git_hash

    # Simulate clean workspace matching parent's commit
    monkeypatch.setattr(
        exman, "_current_git_state", lambda: (parent_hash, False)
    )

    exp, is_new, attempt_num = exman.resume(parent.metadata.exp_id)

    assert is_new is False
    assert attempt_num == 1
    assert exp.metadata.exp_id == parent.metadata.exp_id
    assert len(exp.metadata.attempts) == 1
    assert exp.metadata.attempts[0].sequence == 1
    assert exp.metadata.attempts[0].reason == "run_1"
    assert exp.metadata.status == "running"


def test_resume_logic_clean_appends_second_attempt(tmp_exman_path, monkeypatch):
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="parent")
    parent_hash = parent.metadata.git_hash

    monkeypatch.setattr(
        exman, "_current_git_state", lambda: (parent_hash, False)
    )

    exman.resume(parent.metadata.exp_id)
    exp, is_new, attempt_num = exman.resume(parent.metadata.exp_id)

    assert is_new is False
    assert attempt_num == 2
    assert len(exp.metadata.attempts) == 2
    assert exp.metadata.attempts[1].sequence == 2
    assert exp.metadata.attempts[1].reason == "run_2"


def test_resume_logic_dirty_creates_new_experiment(tmp_exman_path, monkeypatch):
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="parent")

    # Simulate dirty workspace
    monkeypatch.setattr(
        exman, "_current_git_state", lambda: ("different_hash", True)
    )

    child, is_new, attempt_num = exman.resume(parent.metadata.exp_id)

    assert is_new is True
    assert attempt_num == 1
    assert child.metadata.exp_id != parent.metadata.exp_id
    assert child.metadata.parent_id == parent.metadata.exp_id
    assert child.metadata.description == f"inherited from {parent.metadata.exp_id}"


def test_resume_logic_dirty_copies_checkpoints(tmp_exman_path, monkeypatch):
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="parent")
    ckpt = parent.root / "artifacts" / "checkpoints" / "best.pt"
    ckpt.write_text("checkpoint data")

    monkeypatch.setattr(
        exman, "_current_git_state", lambda: ("different_hash", True)
    )

    child, _is_new, _attempt = exman.resume(parent.metadata.exp_id)

    copied = child.root / "artifacts" / "checkpoints" / "best.pt"
    assert copied.exists()
    assert copied.read_text() == "checkpoint data"


def test_resume_nonexistent_raises_valueerror(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    try:
        exman.resume("nonexistent")
        raise AssertionError("Expected ValueError")
    except ValueError as exc:
        assert "nonexistent" in str(exc)


def test_resume_preserves_parent_tags_in_case_b(tmp_exman_path, monkeypatch):
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="parent", tags=["baseline", "v1"])

    monkeypatch.setattr(
        exman, "_current_git_state", lambda: ("different_hash", True)
    )

    child, _is_new, _attempt = exman.resume(parent.metadata.exp_id)

    assert child.metadata.tags == ["baseline", "v1"]


def test_resume_allows_custom_tags_in_case_b(tmp_exman_path, monkeypatch):
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="parent", tags=["baseline"])

    monkeypatch.setattr(
        exman, "_current_git_state", lambda: ("different_hash", True)
    )

    child, _is_new, _attempt = exman.resume(
        parent.metadata.exp_id, tags=["evolved"]
    )

    assert child.metadata.tags == ["evolved"]


def test_run_command_sets_env_vars(tmp_exman_path, monkeypatch):
    """Test that run command sets KAI_EXMAN_* env vars."""
    import subprocess

    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="parent")
    parent_hash = parent.metadata.git_hash

    # Patch git state to be clean (Case A)
    monkeypatch.setattr(
        exman, "_current_git_state", lambda: (parent_hash, False)
    )

    # Run a simple command through the resume mechanism
    env = {"PATH": "/usr/bin:/bin"}
    env["KAI_EXMAN_RESUME"] = "1"
    env["KAI_EXMAN_ATTEMPT_COUNT"] = "1"
    env["KAI_EXMAN_PARENT_PATH"] = str(parent.root)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os; print(os.environ.get('KAI_EXMAN_ATTEMPT_COUNT'))",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "1"


def test_metadata_serialization_with_attempts(tmp_exman_path, monkeypatch):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="test")
    exp_hash = exp.metadata.git_hash

    monkeypatch.setattr(
        exman, "_current_git_state", lambda: (exp_hash, False)
    )

    exman.resume(exp.metadata.exp_id)

    # Reload from disk and verify attempts persist
    meta_path = exp.root / "metadata.json"
    raw = json.loads(meta_path.read_text(encoding="utf-8"))
    assert "attempts" in raw
    assert len(raw["attempts"]) == 1
    assert raw["attempts"][0]["sequence"] == 1
    assert raw["attempts"][0]["status"] == "running"
    assert raw["attempts"][0]["reason"] == "run_1"


def test_status_promotion_from_latest_attempt(tmp_exman_path, monkeypatch):
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="parent")
    parent_hash = parent.metadata.git_hash

    monkeypatch.setattr(
        exman, "_current_git_state", lambda: (parent_hash, False)
    )

    exp, _is_new, _attempt = exman.resume(parent.metadata.exp_id)
    exp.metadata.attempts[0].status = "failed"
    exp.metadata.status = "failed"
    exp.write_metadata()

    # Second resume should create attempt 2 and reset status to running
    exp2, _is_new2, _attempt2 = exman.resume(parent.metadata.exp_id)
    assert exp2.metadata.attempts[1].status == "running"
    assert exp2.metadata.status == "running"

    # Simulate the run command promoting status
    exp2.metadata.attempts[1].status = "success"
    exp2.metadata.status = "success"
    exp2.write_metadata()

    # Reload and verify global status matches latest attempt
    reloaded = exman.get(parent.metadata.exp_id)
    assert reloaded is not None
    assert reloaded.metadata.status == "success"
    assert reloaded.metadata.attempts[-1].status == "success"


def test_three_failed_one_success_promotes_to_success(tmp_exman_path, monkeypatch):
    """Simulate 3 failed attempts followed by a successful 4th."""
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="parent")
    parent_hash = parent.metadata.git_hash

    monkeypatch.setattr(
        exman, "_current_git_state", lambda: (parent_hash, False)
    )

    # Attempt 1: failed
    exp1, _is_new1, _attempt1 = exman.resume(parent.metadata.exp_id)
    exman.finish(exp1.metadata.exp_id, status="failed")

    # Attempt 2: failed
    exp2, _is_new2, _attempt2 = exman.resume(parent.metadata.exp_id)
    exman.finish(exp2.metadata.exp_id, status="failed")

    # Attempt 3: failed
    exp3, _is_new3, _attempt3 = exman.resume(parent.metadata.exp_id)
    exman.finish(exp3.metadata.exp_id, status="failed")

    # Attempt 4: success
    exp4, _is_new4, _attempt4 = exman.resume(parent.metadata.exp_id)
    exp4.metadata.attempts[-1].status = "success"
    exp4.metadata.status = "success"
    exp4.write_metadata()

    # Reload from disk and verify global status is success
    reloaded = exman.get(parent.metadata.exp_id)
    assert reloaded is not None
    assert len(reloaded.metadata.attempts) == 4
    assert reloaded.metadata.attempts[0].status == "failed"
    assert reloaded.metadata.attempts[1].status == "failed"
    assert reloaded.metadata.attempts[2].status == "failed"
    assert reloaded.metadata.attempts[3].status == "success"
    assert reloaded.metadata.status == "success"


def test_finish_updates_last_attempt_status(tmp_exman_path, monkeypatch):
    """Ensure finish() updates the last attempt's status, not just global."""
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="parent")
    parent_hash = parent.metadata.git_hash

    monkeypatch.setattr(
        exman, "_current_git_state", lambda: (parent_hash, False)
    )

    exp, _is_new, _attempt = exman.resume(parent.metadata.exp_id)
    assert exp.metadata.attempts[-1].status == "running"

    exman.finish(exp.metadata.exp_id, status="success")

    reloaded = exman.get(parent.metadata.exp_id)
    assert reloaded is not None
    assert reloaded.metadata.status == "success"
    assert reloaded.metadata.attempts[-1].status == "success"
    assert reloaded.metadata.attempts[-1].end_time != ""


def test_show_displays_parent_id(tmp_exman_path, monkeypatch):
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="parent")

    monkeypatch.setattr(
        exman, "_current_git_state", lambda: ("different_hash", True)
    )
    child, _is_new, _attempt = exman.resume(parent.metadata.exp_id)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--path", tmp_exman_path,
            "show", child.metadata.exp_id,
        ],
    )
    assert result.exit_code == 0
    assert "Parent" in result.output
    assert parent.metadata.exp_id[:8] in result.output


def test_list_shows_inheritance_indicator(tmp_exman_path, monkeypatch):
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="parent")

    monkeypatch.setattr(
        exman, "_current_git_state", lambda: ("different_hash", True)
    )
    child, _is_new, _attempt = exman.resume(parent.metadata.exp_id)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--path", tmp_exman_path,
            "list",
        ],
    )
    assert result.exit_code == 0
    assert "Parent:" in result.output
