import sys
from pathlib import Path

src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src))

from kaiexman.config import ConfigManager


def test_defaults_are_built_in():
    cfg = ConfigManager()
    assert cfg["critical_paths"] == ["src/", "pyproject.toml"]
    assert cfg["ignore_paths"] == ["docs/", "tests/", "README.md", "*.md", ".gitignore"]
    assert cfg["short_id_length"] == 8
    assert cfg["strict_mode"] is False
    assert cfg["trash_max_count"] == 50
    assert cfg["trash_max_size_gb"] == 5.0


def test_cli_override_replaces_default():
    cfg = ConfigManager(cli_overrides={"strict_mode": True})
    assert cfg["strict_mode"] is True
    assert cfg["short_id_length"] == 8


def test_cli_override_completely_replaces_list():
    cfg = ConfigManager(cli_overrides={"critical_paths": ["custom/"]})
    assert cfg["critical_paths"] == ["custom/"]


def test_missing_pyproject_ignored():
    cfg = ConfigManager()
    assert cfg["short_id_length"] == 8


def test_pyproject_loads_tool_section(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.kaiexman]\nshort_id_length = 12\nstrict_mode = true\n")
    cfg = ConfigManager()
    assert cfg["short_id_length"] == 12
    assert cfg["strict_mode"] is True
    assert cfg["critical_paths"] == ["src/", "pyproject.toml"]


def test_cli_overrides_pyproject(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.kaiexman]\nshort_id_length = 12\n")
    cfg = ConfigManager(cli_overrides={"short_id_length": 4})
    assert cfg["short_id_length"] == 4


def test_get_with_fallback():
    cfg = ConfigManager()
    assert cfg.get("nonexistent", "fallback") == "fallback"
