"""Erase everything myGeeKy keeps on this computer (for "Uninstall and erase").

Plain uninstalling keeps your data and tokens, so a reinstall picks up where
you left off. Erasing also removes:
  * the data folder (settings, history, CV text, caches, the sync clone);
  * from the OS keyring: your GitHub tokens, the Product Hunt token and this
    computer's Signals key.
Nothing on GitHub is touched: your private sync repo and your public
mygeeky-beacon repo stay until you delete them there yourself.
"""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

# every keyring entry myGeeKy writes, all keyed by your GitHub username
KEYRING_SERVICES = ("mygeeky-github-token", "mygeeky-beacon-token", "mygeeky-producthunt-token", "mygeeky-signals-key")


def erase_tokens(username: str) -> int:
    """Remove myGeeKy's entries from the OS keyring. Returns how many were there."""
    if not username:
        return 0
    try:
        import keyring
    except Exception:
        return 0
    removed = 0
    for service in KEYRING_SERVICES:
        try:
            if keyring.get_password(service, username) is not None:
                keyring.delete_password(service, username)
                removed += 1
        except Exception:
            pass
    return removed


def _force_remove(func, path, _exc) -> None:
    """git marks its object files read-only; Windows won't delete those otherwise."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def erase_data(data_dir: Path) -> bool:
    """Delete the data folder. True if it's gone."""
    if not data_dir.exists():
        return True
    shutil.rmtree(data_dir, onerror=_force_remove)
    return not data_dir.exists()


def erase_everything() -> list[str]:
    """Tokens first (they need the username from the settings), then the folder."""
    from .config import CONFIG_DIR, DATA_DIR, load_config
    notes = []
    try:
        username = load_config().github_username
    except Exception:
        username = ""
    n = erase_tokens(username)
    notes.append(f"Removed {n} saved token{'s' if n != 1 else ''} and keys from your keyring." if n
                 else "No saved tokens were left in your keyring.")
    notes.append(f"Erased your myGeeKy data ({DATA_DIR})." if erase_data(DATA_DIR)
                 else f"Some of your data couldn't be removed; delete {DATA_DIR} by hand.")
    if CONFIG_DIR != DATA_DIR and CONFIG_DIR.exists():      # Linux/macOS keep settings in their own folder
        notes.append(f"Erased your settings ({CONFIG_DIR})." if erase_data(CONFIG_DIR)
                     else f"Some settings couldn't be removed; delete {CONFIG_DIR} by hand.")
    notes.append("Your GitHub repos (private sync, public mygeeky-beacon) were not touched; delete them on GitHub "
                 "if you no longer want them.")
    return notes
