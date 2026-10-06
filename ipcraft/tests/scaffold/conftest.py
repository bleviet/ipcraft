import shutil
from pathlib import Path

import pytest

# Golden trees contain generated test_*.py files that must never be collected.
collect_ignore_glob = ["golden/*", "golden_import/*", "fixtures/*"]

HERE = Path(__file__).parent
FIXTURES = HERE / "fixtures"
GOLDEN = HERE / "golden"
GOLDEN_IMPORT = HERE / "golden_import"


@pytest.fixture()
def led_project(tmp_path):
    """The led_avmm example copied to ``tmp_path/src``; outputs go to ``tmp_path/out`` (as in the golden trees)."""
    src = tmp_path / "src"
    shutil.copytree(FIXTURES / "led_avmm", src)
    return src / "led_controller_avmm.ip.yml", tmp_path / "out"


def tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}
