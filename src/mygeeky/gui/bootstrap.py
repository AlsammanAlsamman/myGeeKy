"""Make sure Qt (PySide6) is importable before the panel or the setup wizard
starts -- installing it on first use if needed.

Why not a plain pip dependency: PySide6 ships files nested 151 characters
deep. Under the Microsoft Store Python, whose package folder is itself ~125
characters long, that passes Windows' 260-character path limit and the
whole `pip install` fails (unless long paths are enabled, which needs
admin). So `pip install mygeeky` never pulls Qt; the first `mygeeky gui`
does, into the normal site-packages when the paths fit, or else into a
short private folder (`~/.mygeeky/qt`, or $MYGEEKY_QT_DIR) that is put on
sys.path at startup. No admin rights either way.

Only the standard library is imported here.
"""

from __future__ import annotations

import os
import site
import subprocess
import sys
import sysconfig
from pathlib import Path

QT_REQUIREMENT = "PySide6-Essentials>=6.5"
DEEPEST_QT_FILE = 151          # longest path inside a PySide6 wheel, relative to site-packages
WINDOWS_MAX_PATH = 259


def private_qt_dir() -> Path:
    return Path(os.environ.get("MYGEEKY_QT_DIR") or Path.home() / ".mygeeky" / "qt")


def _add_private_dir() -> None:
    d = str(private_qt_dir())
    if Path(d).is_dir() and d not in sys.path:
        sys.path.insert(0, d)
        # PySide6's DLLs sit next to its .pyd files; on Windows they must be findable
        if hasattr(os, "add_dll_directory") and (Path(d) / "PySide6").is_dir():
            for sub in ("PySide6", "shiboken6"):
                if (Path(d) / sub).is_dir():
                    os.add_dll_directory(str(Path(d) / sub))


def qt_available() -> bool:
    _add_private_dir()
    try:
        import PySide6.QtWidgets  # noqa: F401
    except ImportError:
        return False
    return True


def _long_paths_enabled() -> bool:
    if sys.platform != "win32":
        return True
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as k:
            return winreg.QueryValueEx(k, "LongPathsEnabled")[0] == 1
    except OSError:
        return False


def _pip_install_dir() -> str:
    """Where a plain `pip install` would put packages for this Python."""
    purelib = sysconfig.get_paths()["purelib"]
    if os.access(purelib, os.W_OK):
        return purelib
    return site.getusersitepackages()  # pip falls back to a user install


def paths_fit(install_dir: str | None = None) -> bool:
    if _long_paths_enabled():
        return True
    return len(install_dir or _pip_install_dir()) + 1 + DEEPEST_QT_FILE <= WINDOWS_MAX_PATH


def install_qt(log=print) -> bool:
    """pip-install Qt into this Python, or into the private folder when the
    normal location's paths would be too long. True when it worked."""
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", QT_REQUIREMENT]
    if not paths_fit():
        target = private_qt_dir()
        target.mkdir(parents=True, exist_ok=True)
        cmd += ["--target", str(target), "--upgrade"]
        log(f"This Python's package folder is too deep for Qt, so it goes into {target} instead.")
    log("Installing Qt for the myGeeKy panel (about 80 MB, one time only)...")
    if sys.stdout is None:                      # no console of our own: don't flash one for pip
        from .. import winproc
        ok = winproc.run(cmd).returncode == 0
    else:                                       # in a terminal: let pip show its progress there
        ok = subprocess.run(cmd).returncode == 0
    if ok:
        # make a fresh install importable in this same process
        import importlib
        importlib.invalidate_caches()
    return ok and qt_available()


def ensure_qt(interactive: bool | None = None) -> None:
    """Return when PySide6 can be imported; otherwise install it, or exit
    with a clear message."""
    if qt_available():
        return
    if interactive is None:
        interactive = bool(sys.stdin and sys.stdin.isatty())
    if interactive:
        answer = input("The myGeeKy panel needs Qt (about 80 MB, one time). Install it now? [Y/n] ")
        if answer.strip().lower() in ("n", "no"):
            raise SystemExit("OK. Run `mygeeky gui` again whenever you'd like the panel.")
    if not install_qt():
        raise SystemExit(
            "Couldn't install Qt for the panel. Check your internet connection and try again, or run:\n"
            f'  "{sys.executable}" -m pip install "{QT_REQUIREMENT}" --target "{private_qt_dir()}"')


def setup_main() -> None:
    """Entry point for `mygeeky-setup`: Qt first, then the wizard."""
    ensure_qt()
    from .setup_wizard import main
    sys.exit(main())


if __name__ == "__main__":   # `python -m mygeeky.gui.bootstrap`: just make sure Qt is there
    ensure_qt(interactive=False)
    print("Qt is ready.")
