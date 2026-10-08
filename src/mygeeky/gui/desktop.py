"""Desktop integration: run the panel in the background, and give it a place in
the Linux applications menu (with its icon), optionally at sign-in too.

Everything here is per-user (~/.local/share, ~/.config) -- no sudo, nothing
system-wide -- and `mygeeky desktop remove` takes it all back. Windows gets
its Start-menu entry from the installer; macOS isn't handled here yet.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_ID = "mygeeky"            # also the Qt desktop file name, so the dock shows the right icon
ASSETS = Path(__file__).parent / "assets"
ICON_SIZES = (64, 128, 256)


def _xdg(var: str, default: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / default)


def entry_path() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / "applications" / f"{APP_ID}.desktop"


def autostart_path() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "autostart" / f"{APP_ID}.desktop"


def _icon_dir(size: int) -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / "icons" / "hicolor" / f"{size}x{size}" / "apps"


def launch_command() -> list[str]:
    """How to start the panel without a console window."""
    exe = Path(sys.executable)
    if sys.platform == "win32":
        pythonw = exe.with_name("pythonw.exe")
        if pythonw.exists():
            exe = pythonw
    return [str(exe), "-m", "mygeeky.gui.app"]


def desktop_entry(autostart: bool = False) -> str:
    exec_line = " ".join(f'"{a}"' if " " in a else a for a in launch_command())
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Name=myGeeKy",
        "GenericName=Research network panel",
        "Comment=The people, projects, papers and pulse of your field",
        f"Exec={exec_line}",
        f"Icon={APP_ID}",
        "Terminal=false",
        "Categories=Network;Science;Education;",
        "Keywords=github;research;science;network;papers;",
        f"StartupWMClass={APP_ID}",
    ]
    if autostart:
        lines += ["X-GNOME-Autostart-enabled=true", "X-GNOME-Autostart-Delay=10"]
    return "\n".join(lines) + "\n"


def _refresh_menus() -> None:
    """Ask the desktop to notice the new entry (optional tools; fine if missing)."""
    for cmd in (["update-desktop-database", str(entry_path().parent)],
                ["gtk-update-icon-cache", "-q", "-t", str(_icon_dir(64).parents[1])]):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, capture_output=True, check=False)


def install_menu_entry(autostart: bool | None = None) -> list[str]:
    """Add (or update) the applications-menu entry and icons. Returns what changed."""
    if not sys.platform.startswith("linux"):
        return []
    changed = []
    for size in ICON_SIZES:
        src = ASSETS / f"icon_{size}.png"
        if src.exists():
            dst = _icon_dir(size) / f"{APP_ID}.png"
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists() or dst.read_bytes() != src.read_bytes():
                shutil.copyfile(src, dst)
    entry = desktop_entry()
    path = entry_path()
    if not path.exists() or path.read_text(encoding="utf-8") != entry:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(entry, encoding="utf-8")
        path.chmod(0o755)
        changed.append(f"Added myGeeKy to your applications menu ({path}).")
    if autostart is not None:
        auto = autostart_path()
        if autostart:
            auto.parent.mkdir(parents=True, exist_ok=True)
            auto.write_text(desktop_entry(autostart=True), encoding="utf-8")
            changed.append("myGeeKy will open when you sign in.")
        elif auto.exists():
            auto.unlink()
            changed.append("myGeeKy won't open at sign-in any more.")
    elif autostart_path().exists():          # keep the sign-in entry pointing at this Python too
        autostart_path().write_text(desktop_entry(autostart=True), encoding="utf-8")
    if changed:
        _refresh_menus()
    return changed


def remove_menu_entry() -> list[str]:
    removed = []
    for p in [entry_path(), autostart_path()] + [_icon_dir(s) / f"{APP_ID}.png" for s in ICON_SIZES]:
        if p.exists():
            p.unlink()
            removed.append(str(p))
    if removed:
        _refresh_menus()
    return removed


def launch_detached(log_file: Path) -> subprocess.Popen:
    """Start the panel as its own process, free of this terminal: closing the
    terminal (or Ctrl+C) doesn't close myGeeKy. Its output goes to `log_file`."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    out = open(log_file, "ab")
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": out, "stderr": out, "close_fds": True,
                    "cwd": str(Path.home())}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000   # DETACHED | NEW_GROUP | NO_WINDOW
    else:
        kwargs["start_new_session"] = True                             # survives the terminal closing
    return subprocess.Popen(launch_command(), **kwargs)
