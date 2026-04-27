"""Tests for CLI evolution: explicit retry/inherit + default experiment."""

import sys
from pathlib import Path

from click.testing import CliRunner

src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src))


from kaiexman import ExMan
from kaiexman.cli import cli

# ---------------------------------------------------------------------------
# run on existing experiment
# ---------------------------------------------------------------------------


def test_run_on_running_appends_attempt(tmp_exman_path, monkeypatch):
    """run <exp_id> on a running experiment appends an attempt."""
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="run target")

    from kaiexman.models import Attempt

    parent.metadata.attempts.append(
        Attempt(sequence=1, status="running", exit_code=0)
    )
    parent.write_metadata()

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
            parent.metadata.exp_id,
            "--",
            "echo",
            "hello",
        ],
    )
    assert result.exit_code == 0
    reloaded = exman.get(parent.metadata.exp_id)
    assert len(reloaded.metadata.attempts) == 2


def test_run_on_finished_fails(tmp_exman_path, monkeypatch):
    """run <exp_id> on a finished experiment raises a clear error."""
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="finished parent")

    from kaiexman.models import Attempt

    parent.metadata.attempts.append(
        Attempt(sequence=1, status="running", exit_code=0)
    )
    parent.write_metadata()
    exman.finish(parent.metadata.exp_id, summary="Done.")

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
            parent.metadata.exp_id,
            "--",
            "echo",
            "hello",
        ],
    )
    assert result.exit_code != 0
    assert "finished" in result.output.lower()


def test_run_on_aborted_fails(tmp_exman_path, monkeypatch):
    """run <exp_id> on an aborted experiment raises a clear error."""
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="aborted parent")

    from kaiexman.models import Attempt

    parent.metadata.attempts.append(Attempt(sequence=1, status="running"))
    parent.write_metadata()

    last = parent.metadata.attempts[-1]
    last.exit_code = None
    last.status = "aborted"
    parent.write_metadata()
    exman.finish(parent.metadata.exp_id, summary="Aborted by user.")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--path",
            tmp_exman_path,
            "run",
            parent.metadata.exp_id,
            "--",
            "echo",
            "hello",
        ],
    )
    assert result.exit_code != 0
    assert "aborted" in result.output.lower()


# ---------------------------------------------------------------------------
# init --inherit
# ---------------------------------------------------------------------------


def test_init_inherit_on_finished_succeeds(tmp_exman_path, monkeypatch):
    """init --inherit on a finished experiment creates a draft child."""
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="finished parent")

    from kaiexman.models import Attempt

    parent.metadata.attempts.append(
        Attempt(sequence=1, status="running", exit_code=0)
    )
    parent.write_metadata()
    exman.finish(parent.metadata.exp_id, summary="Done.")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--path",
            tmp_exman_path,
            "init",
            "--inherit",
            parent.metadata.exp_id,
            "--description",
            "Child experiment",
        ],
    )
    assert result.exit_code == 0
    experiments = exman.list()
    child = next(
        (e for e in experiments if parent.metadata.exp_id in e.metadata.parent_ids),
        None,
    )
    assert child is not None
    assert child.metadata.description == "Child experiment"
    assert child.metadata.status == "draft"


def test_init_inherit_on_running_fails(tmp_exman_path, monkeypatch):
    """init --inherit on a running experiment raises a clear error."""
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="running parent")

    from kaiexman.models import Attempt

    parent.metadata.attempts.append(
        Attempt(sequence=1, status="running", exit_code=0)
    )
    parent.write_metadata()

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--path",
            tmp_exman_path,
            "init",
            "--inherit",
            parent.metadata.exp_id,
            "--description",
            "Child",
        ],
    )
    assert result.exit_code != 0
    assert "still running" in result.output.lower()


def test_init_inherit_on_aborted_fails(tmp_exman_path, monkeypatch):
    """init --inherit on an aborted experiment raises a clear error."""
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="aborted parent")

    from kaiexman.models import Attempt

    parent.metadata.attempts.append(Attempt(sequence=1, status="running"))
    parent.write_metadata()

    last = parent.metadata.attempts[-1]
    last.exit_code = None
    last.status = "aborted"
    parent.write_metadata()
    exman.finish(parent.metadata.exp_id, summary="Aborted by user.")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--path",
            tmp_exman_path,
            "init",
            "--inherit",
            parent.metadata.exp_id,
            "--description",
            "Child",
        ],
    )
    assert result.exit_code != 0
    assert "aborted" in result.output.lower()


# ---------------------------------------------------------------------------
# retry command (standalone)
# ---------------------------------------------------------------------------


def test_retry_command_appends_attempt(tmp_exman_path, monkeypatch):
    """Standalone retry command appends an attempt to a running experiment."""
    exman = ExMan(root=tmp_exman_path)
    parent = exman.init(description="retry target")

    from kaiexman.models import Attempt

    parent.metadata.attempts.append(
        Attempt(sequence=1, status="running", exit_code=0)
    )
    parent.write_metadata()

    monkeypatch.setattr(
        ExMan, "_current_git_state", lambda _self: (parent.metadata.git_hash, False)
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--path",
            tmp_exman_path,
            "retry",
            parent.metadata.exp_id,
            "--",
            "echo",
            "hello",
        ],
    )
    assert result.exit_code == 0
    reloaded = exman.get(parent.metadata.exp_id)
    assert len(reloaded.metadata.attempts) == 2


# ---------------------------------------------------------------------------
# use command
# ---------------------------------------------------------------------------


def test_use_command_sets_default(tmp_exman_path):
    """use <id> writes the experiment ID to .current."""
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="default candidate")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--path", tmp_exman_path, "use", exp.metadata.exp_id],
    )
    assert result.exit_code == 0
    assert "default experiment set" in result.output.lower()

    current_path = Path(tmp_exman_path) / ".current"
    assert current_path.exists()
    assert current_path.read_text().strip() == exp.metadata.exp_id


def test_use_command_rejects_invalid_id(tmp_exman_path):
    """use with a non-existent ID should fail."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--path", tmp_exman_path, "use", "nonexistent"],
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# default experiment resolution
# ---------------------------------------------------------------------------


def test_finish_uses_default_experiment(tmp_exman_path):
    """finish without exp_id uses the default experiment."""
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="default finish test")

    from kaiexman.models import Attempt

    exp.metadata.attempts.append(Attempt(sequence=1, status="running", exit_code=0))
    exp.write_metadata()

    exman.set_default_exp_id(exp.metadata.exp_id)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--path",
            tmp_exman_path,
            "finish",
            "--summary",
            "Done.",
        ],
    )
    assert result.exit_code == 0
    reloaded = exman.get(exp.metadata.exp_id)
    assert reloaded.metadata.status == "success"


def test_abort_uses_default_experiment(tmp_exman_path):
    """abort without exp_id uses the default experiment."""
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="default abort test")

    from kaiexman.models import Attempt

    exp.metadata.attempts.append(Attempt(sequence=1, status="running"))
    exp.write_metadata()

    exman.set_default_exp_id(exp.metadata.exp_id)

    runner = CliRunner()
    result = runner.invoke(cli, ["--path", tmp_exman_path, "abort"])
    assert result.exit_code == 0
    reloaded = exman.get(exp.metadata.exp_id)
    assert reloaded.metadata.status == "aborted"


def test_show_uses_default_experiment(tmp_exman_path):
    """show without exp_id uses the default experiment."""
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="default show test")

    exman.set_default_exp_id(exp.metadata.exp_id)

    runner = CliRunner()
    result = runner.invoke(cli, ["--path", tmp_exman_path, "show"])
    assert result.exit_code == 0
    assert "default show test" in result.output


def test_tag_uses_default_experiment(tmp_exman_path):
    """tag without exp_id uses the default experiment."""
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="default tag test")

    exman.set_default_exp_id(exp.metadata.exp_id)

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--path", tmp_exman_path, "tag", "baseline"]
    )
    assert result.exit_code == 0
    reloaded = exman.get(exp.metadata.exp_id)
    assert "baseline" in reloaded.metadata.tags


def test_move_uses_default_experiment(tmp_exman_path):
    """move without exp_id uses the default experiment."""
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="default move test")

    exman.set_default_exp_id(exp.metadata.exp_id)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--path", tmp_exman_path, "move", "--group", "eval"],
    )
    assert result.exit_code == 0
    reloaded = exman.get(exp.metadata.exp_id)
    assert reloaded.metadata.group == "eval"


def test_no_default_raises_clear_error(tmp_exman_path):
    """Commands that need a default experiment raise a clear error when none is set."""
    runner = CliRunner()
    result = runner.invoke(
        cli, ["--path", tmp_exman_path, "finish", "--summary", "Done."]
    )
    assert result.exit_code != 0
    assert "no default experiment set" in result.output.lower()


def test_invalid_default_raises_clear_error(tmp_exman_path):
    """An invalid .current file content raises a clear error."""
    current_path = Path(tmp_exman_path) / ".current"
    current_path.write_text("invalid_id_not_16_chars")

    runner = CliRunner()
    result = runner.invoke(cli, ["--path", tmp_exman_path, "show"])
    assert result.exit_code != 0
    assert "no default experiment set" in result.output.lower()
