import os
import sys
import tempfile
from pathlib import Path

import pytest

src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src))


@pytest.fixture
def tmp_exman_path():
    """Provide a temporary directory for ExMan outputs, cleaned up after each test."""
    tmpdir = tempfile.mkdtemp(prefix="exman_test_")
    yield tmpdir
    import shutil

    shutil.rmtree(tmpdir, ignore_errors=True)
