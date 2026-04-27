import json
import sys
import time
from pathlib import Path

src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src))

from kaiexman import ExMan
from kaiexman.config import ConfigManager


def test_remove_moves_to_trash(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="trash test")
    exp_id = exp.metadata.exp_id

    removed, purged = exman.remove(exp_id)
    assert removed is not None
    assert removed.metadata.exp_id == exp_id
    assert purged == []

    # Original location gone
    assert not exp.root.exists()
    # In trash
    trash = exman._trash_dir()
    assert (trash / exp.root.name).exists()


def test_remove_writes_deletion_info(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="info test")
    exman.remove(exp.metadata.exp_id)

    trash = exman._trash_dir()
    trashed = trash / exp.root.name
    info_path = trashed / ".deletion_info"
    assert info_path.exists()

    data = json.loads(info_path.read_text(encoding="utf-8"))
    assert "deleted_at" in data
    assert "original_path" in data


def test_remove_nonexistent_returns_none(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    removed, purged = exman.remove("nonexistent")
    assert removed is None
    assert purged == []


def test_remove_dry_run_does_not_move(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="dry run")
    exp_id = exp.metadata.exp_id

    removed, purged = exman.remove(exp_id, dry_run=True)
    assert removed is not None
    # Original still there
    assert exp.root.exists()
    # Not in trash
    trash = exman._trash_dir()
    assert not (trash / exp.root.name).exists()


def test_clear_trash_permanently_deletes(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="clear test")
    exman.remove(exp.metadata.exp_id)

    trash = exman._trash_dir()
    assert len(list(trash.iterdir())) > 0

    deleted = exman.clear_trash()
    assert len(deleted) == 1
    assert len(list(trash.iterdir())) == 0


def test_clear_trash_dry_run(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="clear dry")
    exman.remove(exp.metadata.exp_id)

    trash = exman._trash_dir()
    before = list(trash.iterdir())

    deleted = exman.clear_trash(dry_run=True)
    assert len(deleted) == 1
    after = list(trash.iterdir())
    assert before == after


def test_ensure_trash_capacity_purges_oldest_by_count(tmp_exman_path):
    config = ConfigManager(
        cli_overrides={"trash_max_count": 2, "trash_max_size_gb": 100.0}
    )
    exman = ExMan(root=tmp_exman_path, config=config)

    exp1 = exman.init(description="first")
    exp2 = exman.init(description="second")
    exp3 = exman.init(description="third")

    exman.remove(exp1.metadata.exp_id)
    time.sleep(0.01)
    exman.remove(exp2.metadata.exp_id)
    time.sleep(0.01)
    exman.remove(exp3.metadata.exp_id)

    trash = exman._trash_dir()
    names = {p.name for p in trash.iterdir() if p.is_dir()}
    # Oldest (exp1) purged, exp2 and exp3 remain
    assert exp1.root.name not in names
    assert exp2.root.name in names
    assert exp3.root.name in names


def test_ensure_trash_capacity_purges_oldest_by_size(tmp_exman_path):
    config = ConfigManager(
        cli_overrides={"trash_max_count": 100, "trash_max_size_gb": 0.0001}
    )
    exman = ExMan(root=tmp_exman_path, config=config)

    exp1 = exman.init(description="first")
    # Write a large file to make it sizable
    (exp1.root / "big.bin").write_bytes(b"x" * 60000)

    exp2 = exman.init(description="second")
    (exp2.root / "big.bin").write_bytes(b"x" * 60000)

    exman.remove(exp1.metadata.exp_id)
    time.sleep(0.01)
    exman.remove(exp2.metadata.exp_id)

    trash = exman._trash_dir()
    names = {p.name for p in trash.iterdir() if p.is_dir()}
    # With tiny size limit, oldest (exp1) should be purged
    assert exp1.root.name not in names


def test_list_excludes_trash(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="list test")
    exman.remove(exp.metadata.exp_id)

    all_exps = exman.list()
    assert len(all_exps) == 0


def test_dir_size_bytes(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp = exman.init(description="size test")
    (exp.root / "data.bin").write_bytes(b"hello" * 100)

    size = exman._dir_size_bytes(exp.root)
    assert size >= 500


def test_trash_items_sorted_by_deletion_time(tmp_exman_path):
    exman = ExMan(root=tmp_exman_path)
    exp1 = exman.init(description="old")
    exp2 = exman.init(description="new")

    exman.remove(exp1.metadata.exp_id)
    time.sleep(0.05)
    exman.remove(exp2.metadata.exp_id)

    items = exman._trash_items()
    assert len(items) == 2
    assert items[0][0].name == exp1.root.name
    assert items[1][0].name == exp2.root.name
