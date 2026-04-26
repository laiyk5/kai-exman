import sys
from pathlib import Path

src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src))

import click
import pytest

from kaiexman import ExMan
from kaiexman.cli import _resolve_exp_id


class _IdGenerator:
    """Callable that yields IDs from a list, then falls back to a default."""

    def __init__(self, ids: list[str], fallback: str = "zzzzzzzzzzzzzzzz"):
        self._ids = iter(ids)
        self._fallback = fallback

    def __call__(self) -> str:
        try:
            return next(self._ids)
        except StopIteration:
            return self._fallback


def test_resolve_full_id(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exman._next_id = lambda: "abc12345deadbeef"
    exman.init(description="full id test")

    result = _resolve_exp_id(exman, "abc12345deadbeef")
    assert result == "abc12345deadbeef"


def test_resolve_unique_prefix(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exman._next_id = lambda: "abc12345deadbeef"
    exman.init(description="prefix test")

    result = _resolve_exp_id(exman, "abc")
    assert result == "abc12345deadbeef"


def test_resolve_ambiguous_prefix(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exman._next_id = _IdGenerator(["abc11111deadbeef", "abc22222cafebabe"])

    exman.init(description="first")
    exman.init(description="second")

    with pytest.raises(click.ClickException) as exc_info:
        _resolve_exp_id(exman, "abc")

    msg = str(exc_info.value)
    assert "Ambiguous prefix 'abc'" in msg
    assert "abc11111deadbeef" in msg
    assert "abc22222cafebabe" in msg


def test_resolve_nonexistent_id(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exman._next_id = lambda: "abc12345deadbeef"
    exman.init(description="existing")

    with pytest.raises(click.ClickException) as exc_info:
        _resolve_exp_id(exman, "xyz99999cafebabe")

    assert "No experiment found starting with 'xyz99999cafebabe'" in str(exc_info.value)
