"""`python -m mygeeky ...` -- the same as the `mygeeky` command, for when
pip's Scripts folder isn't on PATH (common with the Microsoft Store Python).
On Windows it also offers, once, to put that folder on the user's PATH so
plain `mygeeky` works from then on."""

from __future__ import annotations

import os
import sys
import sysconfig
from pathlib import Path


def scripts_dir() -> Path | None:
    """The folder holding mygeeky.exe for this Python, if there is one."""
    for scheme in (None, f"{os.name}_user"):
        try:
            d = Path(sysconfig.get_path("scripts", scheme) if scheme else sysconfig.get_path("scripts"))
        except KeyError:
            continue
        if (d / "mygeeky.exe").exists() or (d / "mygeeky").exists():
            return d
    return None


def on_path(d: Path) -> bool:
    norm = lambda p: os.path.normcase(os.path.normpath(p))  # noqa: E731
    return norm(str(d)) in {norm(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p}


def add_to_user_path(d: Path) -> None:
    """Append `d` to the current user's PATH (HKCU, no admin) and tell
    Windows, so new terminals pick it up."""
    import ctypes
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
        try:
            current, kind = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            current, kind = "", winreg.REG_EXPAND_SZ
        parts = [p for p in current.split(";") if p]
        if str(d) not in parts:
            winreg.SetValueEx(key, "Path", 0, kind, ";".join(parts + [str(d)]))
    HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x1A, 0x2
    ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
                                             SMTO_ABORTIFHUNG, 2000, None)


def offer_path_fix() -> None:
    if sys.platform != "win32" or not (sys.stdin and sys.stdin.isatty() and sys.stdout and sys.stdout.isatty()):
        return
    quiet = {"--version", "--help", "-h", "--json"}
    if len(sys.argv) < 2 or quiet & set(sys.argv[1:]):
        return  # never interrupt scripts, agents or a quick --version
    d = scripts_dir()
    if d is None or on_path(d):
        return
    from .config import DATA_DIR
    marker = DATA_DIR / ".path_offered"
    if marker.exists():
        return
    try:
        answer = input(f"Tip: the `mygeeky` command lives in {d}, which isn't on your PATH.\n"
                       "Add it, so you can just type `mygeeky` in new terminals? [Y/n] ")
        if answer.strip().lower() not in ("n", "no"):
            add_to_user_path(d)
            print("Done. Open a new terminal and `mygeeky` will work.\n")
    except (OSError, EOFError):
        pass
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("1", encoding="utf-8")
    except OSError:
        pass


def run() -> None:
    offer_path_fix()
    from .cli import main
    main(prog_name="mygeeky")


if __name__ == "__main__":
    run()
