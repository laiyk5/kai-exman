"""Tests for the Mandatory Reflection policy (description + summary)."""

import json
import sys
from pathlib import Path

from click.testing import CliRunner

src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src))

import click
import pytest

from kaiexman import ExMan
from kaiexman.cli import cli

# ---------------------------------------------------------------------------
# init: description is mandatory
# ---------------------------------------------------------------------------


def test_init_cli_rejects_missing_description(tmp_exman_path):
    """Non-interactive init without --description should fail."""
    runner = CliRunner()
    result = runner.invoke(
        cli, ["--path", tmp_exman_path, "init", "--group", "default"]
    )
    assert result.exit_code != 0
    assert "description is required" in result.output.lower()


def test_init_cli_accepts_description(tmp_exman_path):
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--path",
            tmp_exman_path,
            "init",
            "--description",
            "Baseline training run",
        ],
    )
    assert result.exit_code == 0
    # Description is sanitized into the path name
    assert "Baseline_training_run" in result.output


# ---------------------------------------------------------------------------
# run: description is mandatory
# ---------------------------------------------------------------------------


def test_run_cli_rejects_missing_description(tmp_exman_path):
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--path", tmp_exman_path, "run", "--", "echo", "hello"],
    )
    assert result.exit_code != 0
    assert "description is required" in result.output.lower()


def test_run_cli_accepts_description(tmp_exman_path):
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--path",
            tmp_exman_path,
            "run",
            "--description",
            "Quick smoke test",
            "--",
            "echo",
            "hello",
        ],
    )
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# resume: description is mandatory and does NOT inherit parent
# ---------------------------------------------------------------------------


def test_resume_cli_rejects_missing_description(tmp_exman_path, monkeypatch):
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="parent")

    monkeypatch.setattr(
        exman, "_current_git_state", lambda: ("different_hash", True)
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--path",
            tmp_exman_path,
            "run",
            "--resume",
            parent.metadata.exp_id,
            "--",
            "echo",
            "hello",
        ],
    )
    assert result.exit_code != 0
    assert "description is required" in result.output.lower()


def test_resume_cli_fork_does_not_inherit_description(
    tmp_exman_path, monkeypatch
):
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="parent desc", tags=["baseline"])

    monkeypatch.setattr(
        exman, "_current_git_state", lambda: ("different_hash", True)
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--path",
            tmp_exman_path,
            "run",
            "--resume",
            parent.metadata.exp_id,
            "--description",
            "Fork with new intent",
            "--",
            "echo",
            "hello",
        ],
    )
    assert result.exit_code == 0

    experiments = exman.list()
    child = next(
        (e for e in experiments if e.metadata.parent_id == parent.metadata.exp_id),
        None,
    )
    assert child is not None
    assert child.metadata.description == "Fork with new intent"
    assert child.metadata.tags == ["baseline"]


# ---------------------------------------------------------------------------
# finish: summary is mandatory
# ---------------------------------------------------------------------------


def test_finish_cli_rejects_missing_summary(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="finish test")
    from kaiexman.models import Attempt

    exp.metadata.attempts.append(
        Attempt(sequence=1, status="running", exit_code=0)
    )
    exp.write_metadata()

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--path", tmp_exman_path, "finish", exp.metadata.exp_id],
    )
    assert result.exit_code != 0
    assert "summary is required" in result.output.lower()


def test_finish_cli_saves_summary_to_metadata(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="finish test")
    from kaiexman.models import Attempt

    exp.metadata.attempts.append(
        Attempt(sequence=1, status="running", exit_code=0)
    )
    exp.write_metadata()

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--path",
            tmp_exman_path,
            "finish",
            "--summary",
            "Model converged cleanly.",
            exp.metadata.exp_id,
        ],
    )
    assert result.exit_code == 0

    meta_path = Path(tmp_exman_path) / "default" / exp.root.name / "metadata.json"
    raw = json.loads(meta_path.read_text())
    assert raw["summary"] == "Model converged cleanly."


# ---------------------------------------------------------------------------
# abort: summary is mandatory
# ---------------------------------------------------------------------------


def test_abort_cli_rejects_missing_summary(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="abort test")
    from kaiexman.models import Attempt

    exp.metadata.attempts.append(Attempt(sequence=1, status="running"))
    exp.write_metadata()

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--path", tmp_exman_path, "abort", exp.metadata.exp_id],
    )
    assert result.exit_code != 0
    assert "summary is required" in result.output.lower()


def test_abort_cli_saves_summary_to_metadata(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="abort test")
    from kaiexman.models import Attempt

    exp.metadata.attempts.append(Attempt(sequence=1, status="running"))
    exp.write_metadata()

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--path",
            tmp_exman_path,
            "abort",
            "--summary",
            "Stopped due to OOM.",
            exp.metadata.exp_id,
        ],
    )
    assert result.exit_code == 0

    meta_path = Path(tmp_exman_path) / "default" / exp.root.name / "metadata.json"
    raw = json.loads(meta_path.read_text())
    assert raw["summary"] == "Stopped due to OOM."


# ---------------------------------------------------------------------------
# list UI: shows Intent and Conclusion
# ---------------------------------------------------------------------------


def test_list_log_shows_intent(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exman.init(description="Training baseline model")

    runner = CliRunner()
    result = runner.invoke(cli, ["--path", tmp_exman_path, "list"])
    assert result.exit_code == 0
    assert "Intent:" in result.output
    assert "Training baseline model" in result.output


def test_list_log_shows_conclusion_for_finished(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="Training baseline model")
    from kaiexman.models import Attempt

    exp.metadata.attempts.append(
        Attempt(sequence=1, status="running", exit_code=0)
    )
    exp.write_metadata()
    exman.finish(exp.metadata.exp_id, summary="Converged to 95% accuracy.")

    runner = CliRunner()
    result = runner.invoke(cli, ["--path", tmp_exman_path, "list"])
    assert result.exit_code == 0
    assert "Conclusion:" in result.output
    assert "Converged to 95% accuracy." in result.output


def test_list_oneline_shows_description(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exman.init(description="Quick eval run")

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--path", tmp_exman_path, "list", "--oneline"]
    )
    assert result.exit_code == 0
    assert "Quick eval run" in result.output


def test_list_tree_truncates_long_description(tmp_exman_path, monkeypatch):
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="A" * 50)

    monkeypatch.setattr(
        exman, "_current_git_state", lambda: ("different_hash", True)
    )
    exman.resume(parent.metadata.exp_id, description="B" * 50)

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--path", tmp_exman_path, "list", "--tree"]
    )
    assert result.exit_code == 0
    # Truncated to 27 chars + "..."
    assert "A" * 27 + "..." in result.output
    assert "B" * 27 + "..." in result.output


# ---------------------------------------------------------------------------
# _require_text helper
# ---------------------------------------------------------------------------


def test_require_text_returns_value_when_provided():
    from kaiexman.cli import _require_text

    assert _require_text("hello", "prompt", "error") == "hello"


def test_require_text_raises_in_non_interactive_mode():
    from kaiexman.cli import _require_text

    with pytest.raises(click.ClickException, match="error msg"):
        _require_text("", "prompt", "error msg")


def test_require_text_strips_comments_and_returns_cleaned_text(monkeypatch):
    from kaiexman.cli import _require_text

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(
        "click.edit",
        lambda text: "# This is a prompt\n\nActual content\n# Another comment",
    )

    result = _require_text("", "prompt", "error msg")
    assert result == "Actual content"


def test_require_text_prefills_template(monkeypatch):
    from kaiexman.cli import _CONCLUSION_TEMPLATE, _require_text

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    captured = {}

    def fake_edit(text):
        captured["text"] = text
        return "# prompt\n\nUser filled this in."

    monkeypatch.setattr("click.edit", fake_edit)

    _require_text("", "prompt", "error", template=_CONCLUSION_TEMPLATE)
    assert "# What worked:" in captured["text"]
    assert "# Next steps:" in captured["text"]


def test_require_text_empty_after_comment_stripping_raises(monkeypatch):
    from kaiexman.cli import _require_text

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("click.edit", lambda text: "# only comments\n  # indented")

    with pytest.raises(click.ClickException, match="error msg"):
        _require_text("", "prompt", "error msg")


# ---------------------------------------------------------------------------
# auto-resume detection
# ---------------------------------------------------------------------------


def test_run_auto_detects_resume_from_first_arg(tmp_exman_path, monkeypatch):
    """If the first positional arg matches an experiment ID, treat as --resume."""
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="parent")

    # Patch at class level because run() creates its own ExMan instance.
    monkeypatch.setattr(
        ExMan, "_current_git_state", lambda _self: (parent.metadata.git_hash, False)
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--path",
            tmp_exman_path,
            "run",
            "-d",
            "resume test",
            parent.metadata.exp_id[:8],
            "--",
            "echo",
            "hello",
        ],
    )
    assert result.exit_code == 0
    # The output should mention resuming, not "Running experiment"
    assert "Resuming experiment" in result.output or "attempt" in result.output.lower()


def test_run_auto_detect_skips_ambiguous_prefix(tmp_exman_path):
    """If the prefix matches multiple experiments, do NOT auto-detect."""
    exman = ExMan(root=tmp_exman_path)
    exman.init(description="exp1")
    exman.init(description="exp2")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--path",
            tmp_exman_path,
            "run",
            "-d",
            "test",
            "echo",
            "hello",
        ],
    )
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# show command displays summary
# ---------------------------------------------------------------------------


def test_show_displays_summary(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="show test")
    from kaiexman.models import Attempt

    exp.metadata.attempts.append(
        Attempt(sequence=1, status="running", exit_code=0)
    )
    exp.write_metadata()
    exman.finish(exp.metadata.exp_id, summary="All good.")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--path",
            tmp_exman_path,
            "show",
            exp.metadata.exp_id,
        ],
    )
    assert result.exit_code == 0
    assert "All good." in result.output
