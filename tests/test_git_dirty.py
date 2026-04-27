import subprocess
import sys
from pathlib import Path

src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src))

from kaiexman.experiment import Experiment
from kaiexman.models import Metadata


def _init_git_repo(path: Path) -> None:
    """Initialize a git repo with an initial commit."""
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    (path / "README.md").write_text("# test")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=path,
        check=True,
        capture_output=True,
    )


def test_git_info_no_repo(tmp_path):
    exp = Experiment(root=tmp_path, metadata=Metadata(exp_id="test1234"))
    git_hash, git_dirty = exp._git_info(cwd=str(tmp_path))
    assert git_hash == ""
    assert git_dirty is False


def test_git_info_clean_repo(tmp_path):
    _init_git_repo(tmp_path)
    exp = Experiment(root=tmp_path, metadata=Metadata(exp_id="test1234"))
    git_hash, git_dirty = exp._git_info(cwd=str(tmp_path))
    assert len(git_hash) == 40
    assert git_dirty is False


def test_git_info_non_critical_change_is_clean(tmp_path):
    _init_git_repo(tmp_path)
    (tmp_path / "README.md").write_text("# modified")
    exp = Experiment(root=tmp_path, metadata=Metadata(exp_id="test1234"))
    git_hash, git_dirty = exp._git_info(cwd=str(tmp_path))
    assert len(git_hash) == 40
    assert git_dirty is False


def test_git_info_critical_change_is_dirty(tmp_path):
    _init_git_repo(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "add src"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "src" / "main.py").write_text("print('world')")
    exp = Experiment(root=tmp_path, metadata=Metadata(exp_id="test1234"))
    git_hash, git_dirty = exp._git_info(cwd=str(tmp_path))
    assert len(git_hash) == 40
    assert git_dirty is True


def test_git_info_untracked_critical_is_dirty(tmp_path):
    _init_git_repo(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "new.py").write_text("# new")
    exp = Experiment(root=tmp_path, metadata=Metadata(exp_id="test1234"))
    git_hash, git_dirty = exp._git_info(cwd=str(tmp_path))
    assert len(git_hash) == 40
    assert git_dirty is True


def test_git_info_untracked_non_critical_is_clean(tmp_path):
    _init_git_repo(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "new.md").write_text("# new doc")
    exp = Experiment(root=tmp_path, metadata=Metadata(exp_id="test1234"))
    git_hash, git_dirty = exp._git_info(cwd=str(tmp_path))
    assert len(git_hash) == 40
    assert git_dirty is False
