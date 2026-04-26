import sys
from pathlib import Path

src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src))

import pytest
from click.testing import CliRunner

from kaiexman import ExMan
from kaiexman.cli import cli
from kaiexman.experiment import validate_tag

# -- Validation ----------------------------------------------------------


def test_validate_tag_accepts_valid_formats():
    valid = [
        "baseline",
        "v1.0",
        "model_v2",
        "experiment-123",
        "A",
        "1",
        "a_b.c-d",
    ]
    for tag in valid:
        validate_tag(tag)  # should not raise


def test_validate_tag_rejects_invalid_characters():
    invalid = [
        "Best Experiment!",
        "tag with spaces",
        "🔥",
        "hello/world",
        "hello\\world",
        "hello@world",
        "hello#world",
        "hello$world",
        "hello%world",
        "hello^world",
        "hello&world",
        "hello*world",
        "hello(world)",
        "hello+world",
        "hello=world",
        "hello[world]",
        "hello{world}",
        "hello|world",
        "hello<world>",
        "hello?world",
        "hello,world",
        "hello;world",
        "hello'world",
        'hello"world',
        "hello`world",
        "hello~world",
        "hello!world",
    ]
    for tag in invalid:
        with pytest.raises(ValueError) as exc_info:
            validate_tag(tag)
        assert "Invalid tag format" in str(exc_info.value)


def test_validate_tag_rejects_leading_special_char():
    with pytest.raises(ValueError):
        validate_tag("-leading-dash")
    with pytest.raises(ValueError):
        validate_tag("_leading-underscore")
    with pytest.raises(ValueError):
        validate_tag(".leading-dot")


def test_validate_tag_rejects_empty_string():
    with pytest.raises(ValueError):
        validate_tag("")


# -- Experiment API ------------------------------------------------------


def test_add_tag_succeeds(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="tag test")
    exp.add_tag("baseline")
    assert "baseline" in exp.metadata.tags


def test_add_tag_is_idempotent(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="idempotent tag")
    exp.add_tag("baseline")
    exp.add_tag("baseline")
    assert exp.metadata.tags == ["baseline"]


def test_add_tag_persists_to_metadata_json(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="persist test")
    exp.add_tag("v1.0")

    # Re-read from disk
    reloaded = exman.get(exp.metadata.exp_id)
    assert reloaded is not None
    assert "v1.0" in reloaded.metadata.tags


def test_add_tag_invalid_raises(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="invalid tag test")
    with pytest.raises(ValueError):
        exp.add_tag("invalid tag!")


def test_remove_tag_succeeds(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="remove tag", tags=["keep", "remove"])
    exp.remove_tag("remove")
    assert "remove" not in exp.metadata.tags
    assert "keep" in exp.metadata.tags


def test_remove_tag_nonexistent_is_noop(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="remove noop")
    exp.remove_tag("nonexistent")  # should not raise
    assert exp.metadata.tags == []


# -- Init validation -----------------------------------------------------


def test_init_with_invalid_tag_raises(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    with pytest.raises(ValueError):
        exman.init(description="bad tags", tags=["valid", "invalid!"])


# -- CLI tag command -----------------------------------------------------


def test_cli_tag_add_succeeds(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="cli tag")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--path", tmp_exman_path, "tag", exp.metadata.exp_id, "baseline"],
    )
    assert result.exit_code == 0
    assert "baseline" in result.output

    reloaded = exman.get(exp.metadata.exp_id)
    assert "baseline" in reloaded.metadata.tags


def test_cli_tag_add_invalid_format(tmp_exman_path):
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--path", tmp_exman_path, "tag", "abc123", "Best Experiment!"],
    )
    assert result.exit_code != 0
    assert "Invalid tag format" in result.output


def test_cli_tag_delete_succeeds(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="cli untag", tags=["baseline"])
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--path",
            tmp_exman_path,
            "tag",
            exp.metadata.exp_id,
            "baseline",
            "-d",
        ],
    )
    assert result.exit_code == 0
    assert "removed" in result.output

    reloaded = exman.get(exp.metadata.exp_id)
    assert "baseline" not in reloaded.metadata.tags


# -- List filter by tag --------------------------------------------------


def test_list_filter_by_tag(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exman.init(description="tagged", tags=["baseline"])
    exman.init(description="untagged")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--path", tmp_exman_path, "list", "--tag", "baseline"],
    )
    assert result.exit_code == 0
    assert "tagged" in result.output
    assert "untagged" not in result.output


# -- Edge: long valid tag ------------------------------------------------


def test_add_long_valid_tag(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="long tag")
    long_tag = "a" * 100
    exp.add_tag(long_tag)
    assert long_tag in exp.metadata.tags
