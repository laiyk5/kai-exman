"""Tests for the list command view modes and sorting engine."""

import sys
from pathlib import Path

from click.testing import CliRunner

src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src))

from kaiexman import cli
from kaiexman.manager import ExMan

# ---------------------------------------------------------------------------
# Sorting engine
# ---------------------------------------------------------------------------


def test_sort_by_created_descending_is_default(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exman.init(description="first")
    exman.init(description="second")

    runner = CliRunner()
    result = runner.invoke(
        cli.cli, ["--path", tmp_exman_path, "list", "--sort", "created"]
    )
    assert result.exit_code == 0
    lines = result.output.strip().split("\n")
    # second should appear before first when descending
    second_idx = next(
        (i for i, line in enumerate(lines) if "second" in line), -1
    )
    first_idx = next(
        (i for i, line in enumerate(lines) if "first" in line), -1
    )
    assert second_idx < first_idx


def test_sort_by_group(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exman.init(description="beta", group="train")
    exman.init(description="alpha", group="eval")

    runner = CliRunner()
    result = runner.invoke(
        cli.cli,
        ["--path", tmp_exman_path, "list", "--sort", "group", "--order", "asc"],
    )
    assert result.exit_code == 0
    eval_idx = result.output.find("eval")
    train_idx = result.output.find("train")
    assert eval_idx < train_idx


def test_sort_by_id(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    e1 = exman.init(description="first")
    e2 = exman.init(description="second")

    runner = CliRunner()
    result = runner.invoke(
        cli.cli,
        ["--path", tmp_exman_path, "list", "--sort", "id", "--order", "asc"],
    )
    assert result.exit_code == 0
    id1 = e1.metadata.exp_id[:8]
    id2 = e2.metadata.exp_id[:8]
    idx1 = result.output.find(id1)
    idx2 = result.output.find(id2)
    # Verify both IDs appear and order matches actual ID sort
    assert idx1 != -1
    assert idx2 != -1
    if id1 < id2:
        assert idx1 < idx2
    else:
        assert idx2 < idx1


def test_sort_by_finished(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exman.init(description="unfinished")
    e2 = exman.init(description="finished")
    from kaiexman.models import Attempt
    e2.metadata.attempts.append(
        Attempt(sequence=1, status="running", exit_code=0)
    )
    e2.write_metadata()
    exman.finish(e2.metadata.exp_id)

    runner = CliRunner()
    result = runner.invoke(
        cli.cli,
        [
            "--path",
            tmp_exman_path,
            "list",
            "--sort",
            "finished",
            "--order",
            "desc",
        ],
    )
    assert result.exit_code == 0
    # finished experiment should appear before unfinished when desc
    finished_idx = result.output.find("finished")
    unfinished_idx = result.output.find("unfinished")
    assert finished_idx < unfinished_idx


def test_sort_and_sort_by_are_mutually_exclusive(tmp_exman_path):
    runner = CliRunner()
    result = runner.invoke(
        cli.cli,
        [
            "--path",
            tmp_exman_path,
            "list",
            "--sort",
            "created",
            "--sort-by",
            "acc",
        ],
    )
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output.lower()


# ---------------------------------------------------------------------------
# Default log view
# ---------------------------------------------------------------------------


def test_log_view_shows_status_and_group(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exman.init(description="baseline", group="train", tags=["v1"])

    runner = CliRunner()
    result = runner.invoke(cli.cli, ["--path", tmp_exman_path, "list"])
    assert result.exit_code == 0
    assert "running" in result.output
    assert "train" in result.output
    assert "v1" in result.output
    assert "baseline" in result.output


def test_log_view_shows_parent_reference(tmp_exman_path, monkeypatch):
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="parent")

    monkeypatch.setattr(
        exman, "_current_git_state", lambda: ("different_hash", True)
    )
    exman.resume(parent.metadata.exp_id)

    runner = CliRunner()
    result = runner.invoke(cli.cli, ["--path", tmp_exman_path, "list"])
    assert result.exit_code == 0
    assert "Parent:" in result.output


# ---------------------------------------------------------------------------
# Oneline view
# ---------------------------------------------------------------------------


def test_oneline_shows_compact_format(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exman.init(description="baseline", group="train", tags=["v1"])

    runner = CliRunner()
    result = runner.invoke(
        cli.cli, ["--path", tmp_exman_path, "list", "--oneline"]
    )
    assert result.exit_code == 0
    assert "RUNNING" in result.output
    assert "train" in result.output
    assert "baseline" in result.output
    assert "v1" in result.output


def test_oneline_shows_inherited_experiments(tmp_exman_path, monkeypatch):
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="parent")

    monkeypatch.setattr(
        exman, "_current_git_state", lambda: ("different_hash", True)
    )
    child, _is_new, _attempt = exman.resume(parent.metadata.exp_id)

    runner = CliRunner()
    result = runner.invoke(
        cli.cli, ["--path", tmp_exman_path, "list", "--oneline"]
    )
    assert result.exit_code == 0
    assert child.metadata.description in result.output
    assert parent.metadata.description in result.output


def test_oneline_shows_finished_at_for_terminal(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="finished_exp")
    from kaiexman.models import Attempt
    exp.metadata.attempts.append(
        Attempt(sequence=1, status="running", exit_code=0)
    )
    exp.write_metadata()
    exman.finish(exp.metadata.exp_id)

    runner = CliRunner()
    result = runner.invoke(
        cli.cli, ["--path", tmp_exman_path, "list", "--oneline"]
    )
    assert result.exit_code == 0
    assert "SUCCESS" in result.output
    # The finished_at timestamp should appear (formatted as _oneline_dt)
    assert "→" in result.output


# ---------------------------------------------------------------------------
# Tree view
# ---------------------------------------------------------------------------


def test_tree_shows_lineage_topology(tmp_exman_path, monkeypatch):
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="parent")

    monkeypatch.setattr(
        exman, "_current_git_state", lambda: ("different_hash", True)
    )
    child, _is_new, _attempt = exman.resume(parent.metadata.exp_id)

    runner = CliRunner()
    result = runner.invoke(
        cli.cli, ["--path", tmp_exman_path, "list", "--tree"]
    )
    assert result.exit_code == 0
    # Root marker (draft parent has no attempts)
    assert "○" in result.output
    # Child connector
    assert "`-- o" in result.output or "|-- o" in result.output
    assert "parent" in result.output
    # Child description is empty (no longer auto-inherited)
    assert "(no description)" in result.output


def test_tree_sorts_only_roots(tmp_exman_path, monkeypatch):
    exman = ExMan(root=tmp_exman_path)
    # Create two root experiments
    root_b = exman.init(description="root_b")
    exman.init(description="root_a")

    monkeypatch.setattr(
        exman, "_current_git_state", lambda: ("different_hash", True)
    )
    child, _is_new, _attempt = exman.resume(root_b.metadata.exp_id)

    runner = CliRunner()
    result = runner.invoke(
        cli.cli,
        ["--path", tmp_exman_path, "list", "--tree", "--sort", "id", "--order", "asc"],
    )
    assert result.exit_code == 0

    # Verify lineage: child appears under root_b, not root_a
    child_short_id = child.metadata.exp_id[:8]
    child_idx = result.output.find(child_short_id)
    root_b_idx = result.output.find("root_b")
    root_a_idx = result.output.find("root_a")
    assert child_idx > root_b_idx
    assert root_a_idx != -1

    # Verify the tree connectors are present (draft roots)
    assert "○" in result.output
    assert "`-- o" in result.output or "|-- o" in result.output


# ---------------------------------------------------------------------------
# Status colors (Rich/TYT mode)
# ---------------------------------------------------------------------------


def test_rich_renderer_produces_output(tmp_exman_path, monkeypatch):
    exman = ExMan(root=tmp_exman_path)
    exman.init(description="running_exp")
    finished = exman.init(description="finished_exp")
    from kaiexman.models import Attempt
    finished.metadata.attempts.append(
        Attempt(sequence=1, status="running", exit_code=0)
    )
    finished.write_metadata()
    exman.finish(finished.metadata.exp_id)

    # Force Rich renderer by mocking TTY detection
    monkeypatch.setattr(cli, "_use_pager", lambda _ctx: True)

    runner = CliRunner()
    result = runner.invoke(cli.cli, ["--path", tmp_exman_path, "list"])
    assert result.exit_code == 0
    assert "running_exp" in result.output
    assert "finished_exp" in result.output
    assert "success" in result.output


# ---------------------------------------------------------------------------
# Short IDs
# ---------------------------------------------------------------------------


def test_short_ids_are_8_chars(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="test")

    runner = CliRunner()
    result = runner.invoke(cli.cli, ["--path", tmp_exman_path, "list"])
    assert result.exit_code == 0
    short_id = exp.metadata.exp_id[:8]
    assert short_id in result.output
    # Full ID should not appear by default
    assert exp.metadata.exp_id not in result.output


def test_full_id_flag_shows_full_id(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="test")

    runner = CliRunner()
    result = runner.invoke(
        cli.cli, ["--path", tmp_exman_path, "list", "--full-id"]
    )
    assert result.exit_code == 0
    assert exp.metadata.exp_id in result.output
