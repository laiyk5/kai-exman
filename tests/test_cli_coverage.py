"""Tests for uncovered CLI paths in cli.py."""

import sys
from pathlib import Path

from click.testing import CliRunner

src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src))

import pytest

from kaiexman import ExMan
from kaiexman.cli import _resolve_run_args, cli

# -----------------------------------------------------------------------------
# _resolve_run_args
# -----------------------------------------------------------------------------


def test_resolve_run_args_empty_raises(tmp_exman_path):
    """Empty args should raise ClickException."""
    exman = ExMan(root=tmp_exman_path)
    exman.init(description="target")
    exman.set_default_exp_id(exman.list()[0].metadata.exp_id)
    with pytest.raises(Exception, match="No command to execute"):
        _resolve_run_args(exman, ())


def test_resolve_run_args_double_dash_uses_default(tmp_exman_path):
    """'--' as first arg uses default experiment."""
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="target")
    exman.set_default_exp_id(exp.metadata.exp_id)
    resolved_id, command = _resolve_run_args(exman, ("--", "echo", "hello"))
    assert resolved_id == exp.metadata.exp_id
    assert command == ["echo", "hello"]


def test_resolve_run_args_double_dash_no_command_raises(tmp_exman_path):
    """'--' with no following command should raise."""
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="target")
    exman.set_default_exp_id(exp.metadata.exp_id)
    with pytest.raises(Exception, match="No command to execute"):
        _resolve_run_args(exman, ("--",))


def test_resolve_run_args_prefix_match(tmp_exman_path):
    """First arg matching exactly one exp prefix is treated as exp_id."""
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="target")
    prefix = exp.metadata.exp_id[:4]
    resolved_id, command = _resolve_run_args(exman, (prefix, "echo", "hello"))
    assert resolved_id == exp.metadata.exp_id
    assert command == ["echo", "hello"]


def test_resolve_run_args_no_prefix_match_uses_default(tmp_exman_path):
    """First arg not matching any exp uses default."""
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="target")
    exman.set_default_exp_id(exp.metadata.exp_id)
    resolved_id, command = _resolve_run_args(exman, ("echo", "hello"))
    assert resolved_id == exp.metadata.exp_id
    assert command == ["echo", "hello"]


def test_resolve_run_args_strips_leading_dashdash(tmp_exman_path):
    """Leading '--' in command is stripped."""
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="target")
    prefix = exp.metadata.exp_id[:4]
    resolved_id, command = _resolve_run_args(exman, (prefix, "--", "echo", "hello"))
    assert resolved_id == exp.metadata.exp_id
    assert command == ["echo", "hello"]


# -----------------------------------------------------------------------------
# list empty state
# -----------------------------------------------------------------------------


def test_list_empty_shows_message(tmp_exman_path):
    """list with no experiments prints a friendly message."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--path", tmp_exman_path, "list"])
    assert result.exit_code == 0
    assert "no experiments found" in result.output.lower()


# -----------------------------------------------------------------------------
# status command
# -----------------------------------------------------------------------------


def test_status_shows_experiment_details(tmp_exman_path):
    """status displays metadata for a valid experiment."""
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="status test", group="train")
    from kaiexman.models import Attempt

    exp.metadata.attempts.append(Attempt(sequence=1, status="running", exit_code=0))
    exp.write_metadata()
    exman.finish(exp.metadata.exp_id, summary="Done.")

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--path", tmp_exman_path, "status", exp.metadata.exp_id]
    )
    assert result.exit_code == 0
    assert "status test" in result.output
    assert "train" in result.output
    assert "Done." in result.output


def test_status_full_id_flag(tmp_exman_path):
    """status --full-id shows the full experiment ID."""
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="status test")

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--path", tmp_exman_path, "status", "--full-id", exp.metadata.exp_id]
    )
    assert result.exit_code == 0
    assert exp.metadata.exp_id in result.output


def test_status_not_found_raises(tmp_exman_path):
    """status with a nonexistent ID should fail."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--path", tmp_exman_path, "status", "nonexistent"])
    assert result.exit_code != 0
    assert "no experiment found" in result.output.lower()


def test_status_with_parent_id(tmp_exman_path, monkeypatch):
    """status shows parent ID when experiment has a parent."""
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="parent")
    from kaiexman.models import Attempt

    parent.metadata.attempts.append(Attempt(sequence=1, status="running", exit_code=0))
    parent.write_metadata()
    exman.finish(parent.metadata.exp_id, summary="Done.")

    monkeypatch.setattr(exman, "_current_git_state", lambda: ("different_hash", True))
    child, _is_new, _attempt = exman.resume(parent.metadata.exp_id, description="child")

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--path", tmp_exman_path, "status", child.metadata.exp_id]
    )
    assert result.exit_code == 0
    assert "Parent:" in result.output


def test_status_with_config_and_metrics(tmp_exman_path):
    """status shows config and best metrics."""
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="status test")
    exp.config = {"lr": 0.01, "epochs": 10}
    exp.write_config()
    exp.log_metrics(step=1, values={"loss": 1.5, "acc": 0.8})
    exp.log_metrics(step=2, values={"loss": 1.0, "acc": 0.9})

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--path", tmp_exman_path, "status", exp.metadata.exp_id]
    )
    assert result.exit_code == 0
    assert "lr:" in result.output
    assert "loss" in result.output
    assert "acc" in result.output


def test_status_with_attempts(tmp_exman_path):
    """status shows attempts table."""
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="status test")
    from kaiexman.models import Attempt

    exp.metadata.attempts.append(
        Attempt(sequence=1, status="running", exit_code=0, reason="first_try")
    )
    exp.write_metadata()

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--path", tmp_exman_path, "status", exp.metadata.exp_id]
    )
    assert result.exit_code == 0
    assert "Attempts:" in result.output
    assert "first_try" in result.output


# -----------------------------------------------------------------------------
# tag command list mode
# -----------------------------------------------------------------------------


def test_tag_list_shows_tags(tmp_exman_path):
    """tag -l lists all tags with counts."""
    exman = ExMan(root=tmp_exman_path)
    exman.init(description="tag test", tags=["v1", "baseline"])

    runner = CliRunner()
    result = runner.invoke(cli, ["--path", tmp_exman_path, "tag", "-l"])
    assert result.exit_code == 0
    assert "v1" in result.output
    assert "baseline" in result.output


def test_tag_list_empty_shows_message(tmp_exman_path):
    """tag -l with no tagged experiments prints a message."""
    exman = ExMan(root=tmp_exman_path)
    exman.init(description="no tags")

    runner = CliRunner()
    result = runner.invoke(cli, ["--path", tmp_exman_path, "tag", "-l"])
    assert result.exit_code == 0
    assert "no tags" in result.output.lower()


def test_tag_list_filtered_by_group(tmp_exman_path):
    """tag -l --group filters tags to a specific group."""
    exman = ExMan(root=tmp_exman_path)
    exman.init(description="train exp", group="train", tags=["v1"])
    exman.init(description="eval exp", group="eval", tags=["v2"])

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--path", tmp_exman_path, "tag", "-l", "--group", "train"]
    )
    assert result.exit_code == 0
    assert "v1" in result.output
    assert "v2" not in result.output


def test_tag_wrong_args_raises(tmp_exman_path):
    """tag with wrong number of args raises an error."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--path", tmp_exman_path, "tag", "a", "b", "c"])
    assert result.exit_code != 0
    assert "requires 1 or 2 arguments" in result.output.lower()


# -----------------------------------------------------------------------------
# group command
# -----------------------------------------------------------------------------


def test_group_list_shows_groups(tmp_exman_path):
    """group -l lists all groups with experiment counts."""
    exman = ExMan(root=tmp_exman_path)
    exman.init(description="train1", group="train")
    exman.init(description="eval1", group="eval")

    runner = CliRunner()
    result = runner.invoke(cli, ["--path", tmp_exman_path, "group", "-l"])
    assert result.exit_code == 0
    assert "train" in result.output
    assert "eval" in result.output


def test_group_list_empty_shows_message(tmp_exman_path):
    """group -l with no experiments prints a message."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--path", tmp_exman_path, "group", "-l"])
    assert result.exit_code == 0
    assert "no experiments found" in result.output.lower()


def test_group_suggest_no_matches_shows_message(tmp_exman_path):
    """group with no suggestions above threshold prints a message."""
    exman = ExMan(root=tmp_exman_path)
    exman.init(description="exp1", group="default")
    exman.init(description="exp2", group="default")

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--path", tmp_exman_path, "group", "--threshold", "0.99"]
    )
    assert result.exit_code == 0
    assert "no group suggestions" in result.output.lower()


def test_group_suggest_shows_recommendations(tmp_exman_path):
    """group shows similarity-based suggestions."""
    exman = ExMan(root=tmp_exman_path)
    exman.init(description="exp1", group="default")
    exman.init(description="exp2", group="default")

    runner = CliRunner()
    result = runner.invoke(cli, ["--path", tmp_exman_path, "group"])
    assert result.exit_code == 0


# -----------------------------------------------------------------------------
# rm command
# -----------------------------------------------------------------------------


def test_rm_moves_to_trash_with_yes(tmp_exman_path):
    """rm --yes moves an experiment to trash."""
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="to delete")

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--path", tmp_exman_path, "rm", "--yes", exp.metadata.exp_id]
    )
    assert result.exit_code == 0
    assert "moved" in result.output.lower()
    assert exman.get(exp.metadata.exp_id) is None


def test_rm_dry_run_shows_would_move(tmp_exman_path):
    """rm --dry-run shows what would happen without acting."""
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="to delete")

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--path", tmp_exman_path, "rm", "--dry-run", exp.metadata.exp_id]
    )
    assert result.exit_code == 0
    assert "would move" in result.output.lower()
    assert exman.get(exp.metadata.exp_id) is not None


def test_rm_clear_trash(tmp_exman_path):
    """rm --clear-trash --yes permanently deletes trashed items."""
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="to delete")
    exman.remove(exp.metadata.exp_id)

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--path", tmp_exman_path, "rm", "--clear-trash", "--yes"]
    )
    assert result.exit_code == 0
    assert "deleted" in result.output.lower()


def test_rm_clear_trash_dry_run(tmp_exman_path):
    """rm --clear-trash --dry-run previews deletions."""
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="to delete")
    exman.remove(exp.metadata.exp_id)

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--path", tmp_exman_path, "rm", "--clear-trash", "--dry-run"]
    )
    assert result.exit_code == 0
    assert "would delete" in result.output.lower()


def test_rm_clear_trash_empty_shows_message(tmp_exman_path):
    """rm --clear-trash on empty trash prints a message."""
    runner = CliRunner()
    result = runner.invoke(
        cli, ["--path", tmp_exman_path, "rm", "--clear-trash", "--yes"]
    )
    assert result.exit_code == 0
    assert "already empty" in result.output.lower()


def test_rm_mark_deletable(tmp_exman_path):
    """rm --mark-deletable flags an experiment for cascade removal."""
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="to mark")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--path", tmp_exman_path, "rm", "--mark-deletable", exp.metadata.exp_id],
    )
    assert result.exit_code == 0
    assert "marked" in result.output.lower()
    reloaded = exman.get(exp.metadata.exp_id)
    assert reloaded.metadata.deletable is True


def test_rm_mark_deletable_dry_run(tmp_exman_path):
    """rm --mark-deletable --dry-run shows what would happen."""
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="to mark")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--path",
            tmp_exman_path,
            "rm",
            "--mark-deletable",
            "--dry-run",
            exp.metadata.exp_id,
        ],
    )
    assert result.exit_code == 0
    assert "would mark" in result.output.lower()


def test_rm_no_exp_id_raises(tmp_exman_path):
    """rm without exp_id and without --clear-trash raises an error."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--path", tmp_exman_path, "rm"])
    assert result.exit_code != 0
    assert "required" in result.output.lower()


def test_rm_child_blocks_with_hint(tmp_exman_path, monkeypatch):
    """rm on a parent with children suggests --mark-deletable."""
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="parent")
    from kaiexman.models import Attempt

    parent.metadata.attempts.append(Attempt(sequence=1, status="running", exit_code=0))
    parent.write_metadata()
    exman.finish(parent.metadata.exp_id, summary="Done.")

    monkeypatch.setattr(exman, "_current_git_state", lambda: ("different_hash", True))
    exman.resume(parent.metadata.exp_id, description="child")

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--path", tmp_exman_path, "rm", "--yes", parent.metadata.exp_id]
    )
    assert result.exit_code != 0
    assert "mark-deletable" in result.output.lower()


# -----------------------------------------------------------------------------
# finish / abort error paths
# -----------------------------------------------------------------------------


def test_finish_runtime_error_path(tmp_exman_path):
    """finish on an experiment with no attempts raises RuntimeError."""
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="finish test")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--path", tmp_exman_path, "finish", "--summary", "Done.", exp.metadata.exp_id],
    )
    assert result.exit_code != 0
    assert "no attempts" in result.output.lower() or "running" in result.output.lower()


def test_abort_value_error_no_attempts(tmp_exman_path):
    """abort on a draft experiment with no attempts raises ValueError."""
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="abort test")

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--path", tmp_exman_path, "abort", exp.metadata.exp_id]
    )
    assert result.exit_code != 0
    assert "no attempts" in result.output.lower()


# -----------------------------------------------------------------------------
# AliasedGroup
# -----------------------------------------------------------------------------


def test_alias_log_redirects_to_list(tmp_exman_path):
    """The 'log' alias redirects to the 'list' command."""
    exman = ExMan(root=tmp_exman_path)
    exman.init(description="alias test")

    runner = CliRunner()
    result = runner.invoke(cli, ["--path", tmp_exman_path, "log"])
    assert result.exit_code == 0
    assert "alias test" in result.output


def test_alias_show_redirects_to_status(tmp_exman_path):
    """The 'show' alias redirects to the 'status' command."""
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="alias test")

    runner = CliRunner()
    result = runner.invoke(cli, ["--path", tmp_exman_path, "show", exp.metadata.exp_id])
    assert result.exit_code == 0
    assert "alias test" in result.output
