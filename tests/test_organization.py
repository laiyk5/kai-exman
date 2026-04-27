"""Tests for the Three-Dimensional Organization System (Group, Lineage, Tag)."""

import json
import sys
from pathlib import Path

import pytest

src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src))

from kaiexman import ExMan
from kaiexman.experiment import Experiment, validate_group
from kaiexman.manager import LockedExperimentError

# ---------------------------------------------------------------------------
# validate_group
# ---------------------------------------------------------------------------


def test_validate_group_accepts_valid():
    validate_group("default")
    validate_group("train")
    validate_group("eval_v1")
    validate_group("ablation-02")


def test_validate_group_rejects_uppercase():
    with pytest.raises(ValueError):
        validate_group("Train")


def test_validate_group_rejects_empty():
    with pytest.raises(ValueError):
        validate_group("")


def test_validate_group_rejects_too_long():
    with pytest.raises(ValueError):
        validate_group("a" * 33)


def test_validate_group_rejects_invalid_chars():
    with pytest.raises(ValueError):
        validate_group("train/eval")
    with pytest.raises(ValueError):
        validate_group("train eval")
    with pytest.raises(ValueError):
        validate_group("-train")


# ---------------------------------------------------------------------------
# init with group
# ---------------------------------------------------------------------------


def test_init_creates_group_subdirectory(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="baseline", group="train")
    assert exp.root.parent.name == "train"
    assert exp.metadata.group == "train"


def test_init_default_group_is_default(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="baseline")
    assert exp.root.parent.name == "default"
    assert exp.metadata.group == "default"


# ---------------------------------------------------------------------------
# list with group filter
# ---------------------------------------------------------------------------


def test_list_returns_all_experiments_across_groups(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    e1 = exman.init(description="train1", group="train")
    e2 = exman.init(description="eval1", group="eval")
    e3 = exman.init(description="train2", group="train")

    all_exps = exman.list()
    assert len(all_exps) == 3
    ids = {e.metadata.exp_id for e in all_exps}
    assert ids == {e1.metadata.exp_id, e2.metadata.exp_id, e3.metadata.exp_id}


def test_list_filters_by_group(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exman.init(description="train1", group="train")
    exman.init(description="eval1", group="eval")
    exman.init(description="train2", group="train")

    train_exps = exman.list(group="train")
    assert len(train_exps) == 2
    assert all(e.metadata.group == "train" for e in train_exps)

    eval_exps = exman.list(group="eval")
    assert len(eval_exps) == 1
    assert eval_exps[0].metadata.group == "eval"


def test_list_empty_group_returns_empty(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    assert exman.list(group="nonexistent") == []


# ---------------------------------------------------------------------------
# get with index cache
# ---------------------------------------------------------------------------


def test_get_uses_index_cache(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="test", group="train")

    # Index should exist after init
    index_path = Path(tmp_exman_path) / "index.json"
    assert index_path.exists()

    retrieved = exman.get(exp.metadata.exp_id)
    assert retrieved is not None
    assert retrieved.metadata.exp_id == exp.metadata.exp_id


def test_get_rebuilds_stale_index(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="test", group="train")

    # Corrupt the index
    index_path = Path(tmp_exman_path) / "index.json"
    index_path.write_text("{}")

    retrieved = exman.get(exp.metadata.exp_id)
    assert retrieved is not None
    assert retrieved.metadata.exp_id == exp.metadata.exp_id


# ---------------------------------------------------------------------------
# move
# ---------------------------------------------------------------------------


def test_move_changes_group_and_directory(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="baseline", group="train")
    old_root = exp.root

    moved = exman.move(exp.metadata.exp_id, "eval")
    assert moved.metadata.group == "eval"
    assert moved.root.parent.name == "eval"
    assert not old_root.exists()
    assert moved.root.exists()

    # Metadata on disk should reflect new group
    raw = json.loads((moved.root / "metadata.json").read_text())
    assert raw["group"] == "eval"


def test_move_to_same_group_is_noop(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="baseline", group="train")
    moved = exman.move(exp.metadata.exp_id, "train")
    assert moved.root == exp.root


def test_move_nonexistent_raises(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    with pytest.raises(ValueError, match="not found"):
        exman.move("nonexistent", "eval")


# ---------------------------------------------------------------------------
# backward compatibility migration
# ---------------------------------------------------------------------------


def test_migration_moves_flat_experiments_to_default(tmp_exman_path):
    # Simulate old v0.1.0 flat layout
    root = Path(tmp_exman_path)
    old_exp = root / "20260427_abc123_test"
    old_exp.mkdir(parents=True)
    meta = {
        "exp_id": "abc123def4567890",
        "timestamp": "2026-04-27T10:00:00",
        "git_hash": "",
        "git_dirty": False,
        "tags": [],
        "data_version": "",
        "description": "legacy experiment",
        "status": "running",
        "parent_id": "",
        "attempts": [],
        "group": "default",
    }
    (old_exp / "metadata.json").write_text(json.dumps(meta))
    (old_exp / "logs").mkdir()
    (old_exp / "artifacts" / "checkpoints").mkdir(parents=True)

    # Creating ExMan should trigger migration
    exman = ExMan(root=tmp_exman_path)
    default_group = root / "default"
    assert default_group.exists()
    assert (default_group / old_exp.name).exists()
    assert not old_exp.exists()

    # Should still be discoverable
    experiments = exman.list()
    assert len(experiments) == 1
    assert experiments[0].metadata.exp_id == "abc123def4567890"


# ---------------------------------------------------------------------------
# index operations
# ---------------------------------------------------------------------------


def test_rebuild_index_creates_correct_structure(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    e1 = exman.init(description="exp1", group="train", tags=["baseline"])
    e2 = exman.init(description="exp2", group="eval", tags=["baseline", "v1"])

    index = exman.rebuild_index()
    assert index["version"] == 1
    assert e1.metadata.exp_id in index["experiments"]
    assert e2.metadata.exp_id in index["experiments"]

    # Tag index
    assert e1.metadata.exp_id in index["tag_index"]["baseline"]
    assert e2.metadata.exp_id in index["tag_index"]["baseline"]
    assert e2.metadata.exp_id in index["tag_index"]["v1"]

    # Group index
    assert e1.metadata.exp_id in index["group_index"]["train"]
    assert e2.metadata.exp_id in index["group_index"]["eval"]


def test_index_updated_on_remove(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="exp1", group="train", tags=["baseline"])
    exman.remove(exp.metadata.exp_id)

    index = exman._load_index()
    assert index is not None
    assert exp.metadata.exp_id not in index["experiments"]
    assert exp.metadata.exp_id not in index["tag_index"].get("baseline", [])
    assert exp.metadata.exp_id not in index["group_index"].get("train", [])


# ---------------------------------------------------------------------------
# suggest_groups
# ---------------------------------------------------------------------------


def test_suggest_groups_based_on_config_similarity(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exman.init(
        description="train1", group="train", config={"lr": 0.01, "epochs": 100}
    )
    exman.init(
        description="train2", group="train", config={"lr": 0.02, "epochs": 200}
    )
    exman.init(
        description="orphan", group="default", config={"lr": 0.01, "epochs": 100}
    )

    suggestions = exman.suggest_groups()
    assert len(suggestions) >= 1
    # The orphan experiment should be suggested to move to "train"
    orphan_suggestion = next(
        (s for s in suggestions if s[0].metadata.group == "default"), None
    )
    assert orphan_suggestion is not None
    assert orphan_suggestion[1] == "train"
    assert orphan_suggestion[2] == 1.0  # identical config keys


def test_suggest_groups_respects_threshold(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exman.init(description="train1", group="train", config={"lr": 0.01})
    exman.init(
        description="orphan",
        group="default",
        config={"lr": 0.01, "epochs": 100},
    )

    suggestions = exman.suggest_groups()
    # Jaccard similarity = 1/2 = 0.5, which meets the default threshold
    # Both directions are suggested (train1 -> default, orphan -> train)
    assert len(suggestions) == 2
    groups = {s[1] for s in suggestions}
    assert "train" in groups
    assert "default" in groups


def test_suggest_groups_empty_config_returns_empty(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exman.init(description="train1", group="train")
    exman.init(description="train2", group="train")

    suggestions = exman.suggest_groups()
    assert suggestions == []


# ---------------------------------------------------------------------------
# resume with group
# ---------------------------------------------------------------------------


def test_resume_case_a_ignores_group_parameter(tmp_exman_path, monkeypatch):
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="parent", group="train")
    parent_hash = parent.metadata.git_hash

    monkeypatch.setattr(
        exman, "_current_git_state", lambda: (parent_hash, False)
    )

    # Case A: group parameter should be ignored
    exp, is_new, attempt_num = exman.resume(
        parent.metadata.exp_id, group="eval"
    )
    assert is_new is False
    assert exp.metadata.group == "train"
    assert exp.root.parent.name == "train"


def test_resume_case_b_honors_group_parameter(tmp_exman_path, monkeypatch):
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="parent", group="train")

    monkeypatch.setattr(
        exman, "_current_git_state", lambda: ("different_hash", True)
    )

    child, is_new, attempt_num = exman.resume(
        parent.metadata.exp_id, group="eval"
    )
    assert is_new is True
    assert child.metadata.group == "eval"
    assert child.root.parent.name == "eval"
    assert child.metadata.parent_id == parent.metadata.exp_id


# ---------------------------------------------------------------------------
# Experiment.root mutation (used by move)
# ---------------------------------------------------------------------------


def test_experiment_root_is_mutable():
    """Verify Experiment.root can be reassigned (used by ExMan.move)."""
    from kaiexman.models import Metadata

    meta = Metadata(exp_id="test123")
    exp = Experiment(root=Path("/old/path"), metadata=meta)
    exp.root = Path("/new/path")
    assert str(exp.root) == "/new/path"


# ---------------------------------------------------------------------------
# Terminal state lock
# ---------------------------------------------------------------------------


def test_resume_blocks_terminal_success(tmp_exman_path, monkeypatch):
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="parent", group="train")
    parent_hash = parent.metadata.git_hash

    # Finish the experiment (terminal state)
    exman.finish(parent.metadata.exp_id, status="success")

    monkeypatch.setattr(
        exman, "_current_git_state", lambda: (parent_hash, False)
    )

    with pytest.raises(LockedExperimentError, match="terminal state"):
        exman.resume(parent.metadata.exp_id)


def test_resume_blocks_terminal_finished(tmp_exman_path, monkeypatch):
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="parent", group="train")
    parent_hash = parent.metadata.git_hash

    # Finish with legacy "finished" status (still terminal)
    exman.finish(parent.metadata.exp_id, status="finished")

    monkeypatch.setattr(
        exman, "_current_git_state", lambda: (parent_hash, False)
    )

    with pytest.raises(LockedExperimentError, match="terminal state"):
        exman.resume(parent.metadata.exp_id)


def test_resume_allows_non_terminal(tmp_exman_path, monkeypatch):
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="parent", group="train")
    parent_hash = parent.metadata.git_hash

    monkeypatch.setattr(
        exman, "_current_git_state", lambda: (parent_hash, False)
    )

    # Experiment is still "running" — should be allowed
    exp, is_new, attempt_num = exman.resume(parent.metadata.exp_id)
    assert is_new is False
    assert attempt_num == 1
    assert len(exp.metadata.attempts) == 1


def test_finish_defaults_to_success(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="test")
    finished = exman.finish(exp.metadata.exp_id)
    assert finished is not None
    assert finished.metadata.status == "success"


def test_index_includes_status(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="test", group="train")
    exman.finish(exp.metadata.exp_id, status="success")

    index = exman._load_index()
    assert index is not None
    entry = index["experiments"][exp.metadata.exp_id]
    assert entry["status"] == "success"
