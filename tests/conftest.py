"""Keep every test away from the user's real myGeeKy data.

The real data dir is synced to the user's private GitHub repo, so a test
that logs suggestions/training rows/model history there doesn't just
pollute this machine -- it gets pushed and shows up as fake suggestions on
every machine. This autouse fixture repoints every path constant under the
real CONFIG_DIR/DATA_DIR, in every already-imported mygeeky module (each
`from .config import X` makes its own binding), to a per-test temp dir.
Tests that set their own paths (e.g. the sync tests) still win, since their
monkeypatching runs after this.
"""

import sys
from pathlib import Path

import pytest

import mygeeky.beacon  # noqa: F401 -- import everything that binds paths before patching
import mygeeky.cli  # noqa: F401
import mygeeky.setup_api  # noqa: F401
import mygeeky.config as config_module
import mygeeky.gui.app  # noqa: F401
import mygeeky.storage  # noqa: F401
import mygeeky.sync  # noqa: F401

REAL_ROOTS = (Path(config_module.CONFIG_DIR), Path(config_module.DATA_DIR))


def _under_real_root(value: Path) -> tuple[Path, Path] | None:
    for root in REAL_ROOTS:
        try:
            return root, value.relative_to(root)
        except ValueError:
            continue
    return None


@pytest.fixture(autouse=True)
def _isolate_real_data(tmp_path, monkeypatch):
    fake_roots = {REAL_ROOTS[0]: tmp_path / "config", REAL_ROOTS[1]: tmp_path / "data"}
    for name, module in list(sys.modules.items()):
        if not (name == "mygeeky" or name.startswith("mygeeky.")) or module is None:
            continue
        for attr, value in list(vars(module).items()):
            if attr.isupper() and isinstance(value, Path):
                hit = _under_real_root(value)
                if hit:
                    root, rel = hit
                    monkeypatch.setattr(module, attr, fake_roots[root] / rel)
