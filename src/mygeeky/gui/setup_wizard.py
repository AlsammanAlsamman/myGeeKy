"""The myGeeKy installer: a Next -> Next -> Finish wizard.

Shipped two ways:
- `MyGeeKySetup.exe` (built by installer/build.py with PyInstaller), which
  carries the myGeeKy wheel inside it and installs or updates it into the
  user's own Python;
- `mygeeky setup`, the same wizard from an existing install (re-configure,
  or update from PyPI).

Deliberately imports only PySide6 and the standard library: in the .exe,
myGeeKy itself isn't importable until the wizard has installed it. Every
step after the install runs in the target Python through
`python -m mygeeky.setup_api` (tokens go over stdin, never argv).

Nothing here follows anyone, and nothing is published without a checkbox
the user ticked themselves.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QThread, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

APP = "myGeeKy"
MIN_PY = (3, 9)
from .. import winproc  # noqa: E402

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FROZEN = getattr(sys, "frozen", False)
WINDOWS = sys.platform == "win32"     # elsewhere (Linux, macOS) setup runs inside myGeeKy's own Python
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
ASSETS = BUNDLE_DIR / "assets" if FROZEN else Path(__file__).parent / "assets"
READ_TOKEN_URL = "https://github.com/settings/personal-access-tokens/new"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\myGeeKy"

STYLE = """
QWidget { background-color: #15151f; color: #f0f0f5; }
QLabel, QCheckBox, QRadioButton { background: transparent; }
QLabel { color: #f0f0f5; font-size: 13px; }
QLabel#muted { color: rgba(240,240,245,160); font-size: 12px; }
QLabel#title { font-size: 22px; font-weight: 700; }
QLabel#ok { color: #34d399; }
QLabel#err { color: #f87171; }
QLineEdit, QPlainTextEdit { background: #1f1f2c; color: #f0f0f5; border: 1px solid #34344a;
    border-radius: 8px; padding: 6px 8px; selection-background-color: #7a5cff; }
QLineEdit:focus { border-color: #7fd8ff; }
QPlainTextEdit { font-family: Consolas, monospace; font-size: 11px; }
QPushButton { background: #2a2a3c; color: #f0f0f5; border: none; border-radius: 8px;
    padding: 7px 16px; font-size: 13px; }
QPushButton:hover { background: #3a3a52; }
QPushButton:disabled { color: #77778a; }
QPushButton#primary { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #ff6fd8, stop:1 #7a5cff); }
QCheckBox, QRadioButton { color: #f0f0f5; font-size: 13px; spacing: 8px; }
QCheckBox::indicator, QRadioButton::indicator { width: 15px; height: 15px; border: 1.5px solid #6b6b8a;
    background: #1f1f2c; }
QCheckBox::indicator { border-radius: 4px; }
QRadioButton::indicator { border-radius: 8px; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked { background: #7a5cff; border-color: #7fd8ff; }
QFrame#stepCard { background: #1c1c29; border: 1px solid #2f2f45; border-radius: 10px; }
QFrame#stepCard:disabled { background: #17171f; border-color: #24243a; }
QLabel#stepTitle { font-size: 14px; font-weight: 700; }
QLabel:disabled { color: #6b6b80; }
QProgressBar { background: #1f1f2c; border: none; border-radius: 4px; height: 8px; }
QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #ff6fd8, stop:1 #7a5cff);
    border-radius: 4px; }
"""


# --------------------------------------------------------------------------- errors and the setup log
SETUP_LOG = Path.home() / ".mygeeky" / "setup.log"
PYTHON_ORG_INSTALLER = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"

# What a missing program is, in words a user can act on
PROGRAMS = {
    "winget": "winget (Windows' app installer)",
    "powershell": "PowerShell",
    "schtasks": "Windows Task Scheduler (schtasks)",
    "py": "the Python launcher (py)",
    "where": "the Windows 'where' command",
}


class SetupError(RuntimeError):
    """A failure with a message meant for the user (it names what went wrong)."""


def log(message: str) -> None:
    """Append to ~/.mygeeky/setup.log; logging must never break setup itself.
    Tokens never reach this: they only travel on stdin, which isn't logged."""
    try:
        from datetime import datetime
        SETUP_LOG.parent.mkdir(parents=True, exist_ok=True)
        with SETUP_LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {message}\n")
    except OSError:
        pass


def _program_name(program: str) -> str:
    stem = Path(program).stem.lower()
    if stem.startswith("python"):
        return f"Python ({program})"
    return PROGRAMS.get(stem, Path(program).name)


def _start_error(cmd: list[str], exc: BaseException) -> SetupError:
    program = cmd[0]
    if isinstance(exc, FileNotFoundError):
        if Path(program).stem.lower().startswith("python"):
            msg = (f"Python wasn't found at {program}. It may have been moved or uninstalled. "
                   "Run this setup again and it will set Python up.")
        else:
            msg = f"Couldn't start {_program_name(program)}: it isn't installed on this PC (or isn't on PATH)."
    elif isinstance(exc, subprocess.TimeoutExpired):
        msg = f"{_program_name(program)} took too long and was stopped."
    else:
        msg = f"Couldn't start {_program_name(program)}: {getattr(exc, 'strerror', None) or exc}"
    log(f"ERROR {msg} [{type(exc).__name__}: {exc}]")
    return SetupError(msg)


def describe(exc: BaseException) -> str:
    """One readable sentence for any failure, naming the file or program."""
    if isinstance(exc, SetupError):
        return str(exc)
    from ..errors import describe as describe_any
    return describe_any(exc)


# --------------------------------------------------------------------------- environment (no Qt)
def _run(cmd: list[str], stdin: str | None = None, timeout: int = 600) -> subprocess.CompletedProcess:
    """subprocess.run that never surfaces a bare 'WinError 2': a missing
    program becomes a SetupError naming it. Output is logged; stdin is not."""
    log("run: " + " ".join(cmd[:3]) + (" ..." if len(cmd) > 3 else ""))
    try:
        r = winproc.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout,
                           creationflags=NO_WINDOW, encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise _start_error(cmd, exc) from exc
    if r.returncode != 0:
        log(f"  exit {r.returncode}: {(r.stderr or r.stdout).strip()[-500:]}")
    return r


def _popen(cmd: list[str], **kwargs) -> subprocess.Popen:
    log("start: " + " ".join(cmd[:3]) + (" ..." if len(cmd) > 3 else ""))
    try:
        return winproc.popen(cmd, **kwargs)
    except OSError as exc:
        raise _start_error(cmd, exc) from exc


def python_version(exe: str) -> tuple[int, int] | None:
    try:
        r = _run([exe, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"], timeout=30)
        major, minor = r.stdout.split()
        return int(major), int(minor)
    except Exception:
        return None


def find_python() -> str | None:
    """A Python >= 3.9 to install into: this one when not frozen, else the
    py launcher's, then python on PATH (skipping the Microsoft Store stub),
    then the usual per-user install folders."""
    if not FROZEN:
        return sys.executable
    candidates: list[str] = []
    try:
        r = _run(["py", "-3", "-c", "import sys; print(sys.executable)"], timeout=30)
        if r.returncode == 0:
            candidates.append(r.stdout.strip())
    except Exception:
        pass
    try:
        r = _run(["where", "python"], timeout=30)
        candidates += [p.strip() for p in r.stdout.splitlines() if "WindowsApps" not in p]
    except Exception:
        pass
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python"
    if local.exists():
        candidates += [str(p) for p in sorted(local.glob("Python3*/python.exe"), reverse=True)]
    for exe in candidates:
        if "WindowsApps" in exe:
            # The Microsoft Store Python installs packages so deep that PySide6
            # passes Windows' 260-character path limit; set up a regular one instead.
            continue
        v = python_version(exe)
        if v and v >= MIN_PY:
            return exe
    return None


def install_python(say: Callable[[str], Any]) -> str | None:
    """Set up a per-user Python 3.12 (no admin): winget when this PC has it,
    otherwise the official installer from python.org. Returns its path."""
    say("No usable Python found, so setting up Python 3.12 just for you...")
    try:
        r = _run(["winget", "install", "-e", "--id", "Python.Python.3.12", "--scope", "user", "--silent",
                  "--accept-package-agreements", "--accept-source-agreements"], timeout=1200)
        if r.returncode == 0 and find_python():
            return find_python()
        say("winget couldn't install Python, so downloading it from python.org instead...")
    except SetupError:
        say("winget (Windows' app installer) isn't on this PC, so downloading Python from python.org instead...")
    import tempfile
    import urllib.request
    target = Path(tempfile.gettempdir()) / Path(PYTHON_ORG_INSTALLER).name
    try:
        log(f"download {PYTHON_ORG_INSTALLER}")
        urllib.request.urlretrieve(PYTHON_ORG_INSTALLER, target)
    except OSError as exc:
        raise SetupError(f"Couldn't download Python from python.org ({exc}). Check your internet "
                         "connection and try again.") from exc
    say("Installing Python 3.12 (about a minute)...")
    r = _run([str(target), "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_test=0",
              "Include_doc=0", "Include_launcher=0", "Shortcuts=0"], timeout=1200)
    if r.returncode != 0:
        raise SetupError(f"The Python installer stopped with code {r.returncode}. Details are in {SETUP_LOG}.")
    return find_python()


GIT_RELEASES_API = "https://api.github.com/repos/git-for-windows/git/releases/latest"


def find_git() -> str | None:
    import shutil
    found = shutil.which("git")
    if found:
        return found
    for base, rel in ((os.environ.get("LOCALAPPDATA", ""), "Programs/Git/cmd/git.exe"),
                      (os.environ.get("ProgramFiles", r"C:\Program Files"), "Git/cmd/git.exe")):
        if base and (Path(base) / rel).exists():
            return str(Path(base) / rel)
    return None


def put_on_path(exe: str) -> None:
    """So the steps that follow (child processes) find a program installed a moment ago."""
    folder = str(Path(exe).parent)
    if folder not in os.environ.get("PATH", ""):
        os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")


def install_git(say: Callable[[str], Any]) -> str | None:
    """Git for Windows just for this user (no admin): winget when this PC has
    it, otherwise the official installer from Git for Windows' GitHub releases."""
    say("Installing Git (needed for sync), just for you...")
    try:
        r = _run(["winget", "install", "-e", "--id", "Git.Git", "--scope", "user", "--silent",
                  "--accept-package-agreements", "--accept-source-agreements"], timeout=1200)
        if r.returncode == 0 and find_git():
            return find_git()
        say("winget couldn't install Git, so downloading it from Git for Windows' releases instead...")
    except SetupError:
        say("winget isn't on this PC, so downloading Git from Git for Windows' releases instead...")
    import re
    import tempfile
    import urllib.request
    try:
        with urllib.request.urlopen(GIT_RELEASES_API, timeout=30) as resp:
            release = json.loads(resp.read().decode("utf-8"))
        asset = next(a for a in release.get("assets", [])
                     if re.fullmatch(r"Git-[\d.]+-64-bit\.exe", a.get("name", "")))
        target = Path(tempfile.gettempdir()) / asset["name"]
        log(f"download {asset['browser_download_url']}")
        urllib.request.urlretrieve(asset["browser_download_url"], target)
    except (OSError, StopIteration, ValueError, KeyError) as exc:
        raise SetupError(f"Couldn't download Git ({exc}). Install it yourself from "
                         "https://git-scm.com/download/win, then run setup again.") from exc
    say("Installing Git (a minute or two)...")
    r = _run([str(target), "/VERYSILENT", "/NORESTART", "/NOCANCEL", "/SP-", "/SUPPRESSMSGBOXES",
              "/CURRENTUSER"], timeout=1200)
    if r.returncode != 0:
        raise SetupError(f"The Git installer stopped with code {r.returncode}. Details are in {SETUP_LOG}.")
    return find_git()


def pythonw_for(python: str) -> str:
    w = Path(python).with_name("pythonw.exe")
    return str(w) if w.exists() else python


def installed_info(python: str) -> dict[str, Any]:
    """{"version": "0.3.0" | None, "editable": bool}"""
    r = _run([python, "-m", "pip", "show", "mygeeky"], timeout=120)
    if r.returncode != 0:
        return {"version": None, "editable": False}
    version = re.search(r"^Version:\s*(\S+)", r.stdout, re.M)
    return {"version": version.group(1) if version else None,
            "editable": "Editable project location" in r.stdout}


def bundled_wheel() -> Path | None:
    wheels = sorted((BUNDLE_DIR / "payload").glob("mygeeky-*.whl")) if FROZEN else []
    return wheels[-1] if wheels else None


def wheel_version(wheel: Path | None) -> str | None:
    return wheel.name.split("-")[1] if wheel else None


def api(python: str, action: str, payload: dict[str, Any] | None = None, timeout: int = 600) -> dict[str, Any]:
    """Run one setup_api step in the target Python."""
    try:
        r = _run([python, "-m", "mygeeky.setup_api", action], stdin=json.dumps(payload or {}), timeout=timeout)
    except SetupError as exc:
        return {"ok": False, "error": str(exc)}
    for line in reversed(r.stdout.strip().splitlines()):
        try:
            result = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not result.get("ok"):
            log(f"step '{action}' failed: {result.get('error')}")
            if result.get("details"):
                log("  details:\n" + result["details"].rstrip())
        return result
    # no JSON answer: myGeeKy itself crashed; its last line usually says why
    output = (r.stderr or r.stdout).strip()
    log(f"step '{action}' crashed:\n{output[-3000:]}")
    last = next((ln.strip() for ln in reversed(output.splitlines()) if ln.strip()), "")
    if "No module named 'mygeeky'" in output or 'No module named "mygeeky"' in output:
        return {"ok": False, "error": f"myGeeKy isn't installed in {python}. Go back and run the install step again."}
    return {"ok": False, "error": f"The '{action}' step failed: {last or 'no answer from myGeeKy'}"}


def stop_running_panels() -> int:
    """Close open myGeeKy panels so they restart on the new version."""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
          "Where-Object { $_.CommandLine -match 'mygeeky\\.gui' -and $_.CommandLine -notmatch 'setup_wizard|uninstall_wizard' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force; 1 } | Measure-Object | "
          "Select-Object -ExpandProperty Count")
    try:
        r = _run(["powershell", "-NoProfile", "-Command", ps], timeout=60)
        return int(r.stdout.strip() or 0)
    except Exception:
        return 0


def package_dir(python: str) -> str | None:
    r = _run([python, "-c", "import mygeeky.gui, os; print(os.path.dirname(mygeeky.gui.__file__))"], timeout=60)
    return r.stdout.strip() or None if r.returncode == 0 else None


def make_shortcut(path: Path, target: str, args: str, icon: str | None) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    ps = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK); "
          "$s.TargetPath = $env:TARGET; $s.Arguments = $env:ARGS; "
          "$s.WorkingDirectory = $env:USERPROFILE; $s.Description = 'myGeeKy'; "
          "if ($env:ICON) { $s.IconLocation = $env:ICON }; $s.Save()")
    env = {**os.environ, "LNK": str(path), "TARGET": target, "ARGS": args, "ICON": icon or ""}
    try:
        r = winproc.run(["powershell", "-NoProfile", "-Command", ps], env=env, capture_output=True,
                           text=True, creationflags=NO_WINDOW, timeout=60)
    except Exception as exc:
        log(f"ERROR couldn't create the shortcut {path}: {_start_error(['powershell'], exc)}")
        return False
    if r.returncode != 0:
        log(f"ERROR couldn't create the shortcut {path}: {r.stderr.strip()[-300:]}")
    return r.returncode == 0


def shortcut_paths() -> dict[str, Path]:
    appdata = Path(os.environ.get("APPDATA", ""))
    programs = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return {
        "start_menu": programs / f"{APP}.lnk",
        "startup": programs / "Startup" / f"{APP}.lnk",
        "desktop": Path.home() / "Desktop" / f"{APP}.lnk",
    }


def register_uninstaller(python: str, version: str, icon: str | None) -> None:
    """An entry in Settings -> Apps -> Installed apps (per user, no admin)."""
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
        values = {
            "DisplayName": APP,
            "DisplayVersion": version,
            "Publisher": "Alsamman M. Alsamman",
            "URLInfoAbout": "https://github.com/AlsammanAlsamman/myGeeKy",
            "UninstallString": f'"{pythonw_for(python)}" -m mygeeky.gui.setup_wizard --uninstall',
            "DisplayIcon": icon or "",
        }
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        for name in ("NoModify", "NoRepair"):
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, 1)


def remove_install_script_folder() -> list[str]:
    """If install.sh put myGeeKy in its own folder, remove that folder and the
    ~/.local/bin/mygeeky link to it (this process can finish: Linux keeps the
    open files until it exits)."""
    import shutil
    app_dir = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "mygeeky-app"
    try:
        inside = Path(sys.prefix).resolve().is_relative_to(app_dir.resolve())
    except (OSError, ValueError):
        inside = False
    if not app_dir.exists() or not inside:
        return []
    link = Path.home() / ".local" / "bin" / "mygeeky"
    try:
        if link.is_symlink() and str(app_dir) in os.readlink(link):
            link.unlink()
    except OSError:
        pass
    shutil.rmtree(app_dir, ignore_errors=True)
    return [f"Removed myGeeKy's own folder ({app_dir}) and the mygeeky command."]


def uninstall(python: str, erase: bool = False) -> list[str]:
    """Remove shortcuts, the weekly task, the package and the Apps entry. Your
    data and tokens stay (a reinstall picks up where you left off) unless
    `erase`, which also removes them (see uninstall.py)."""
    notes = []
    stop_running_panels()
    if erase:   # before pip removes the package: erasing needs it
        from .. import uninstall as un
        notes += un.erase_everything()
    if sys.platform == "win32":
        for p in shortcut_paths().values():
            if p.exists():
                p.unlink()
        try:
            _run(["schtasks", "/Delete", "/TN", "myGeeKyWeeklyRun", "/F"], timeout=60)
        except SetupError:
            pass  # no Task Scheduler, so there's no weekly task to remove either
    else:
        try:
            from . import desktop
            desktop.remove_menu_entry()
            from .. import scheduler
            scheduler.remove()
        except Exception:
            pass
        notes += remove_install_script_folder()
    try:
        r = _run([python, "-m", "pip", "uninstall", "-y", "mygeeky"], timeout=300)
        notes.append("Removed the myGeeKy package." if r.returncode == 0 else
                     f"pip couldn't remove the package (details in {SETUP_LOG}).")
    except SetupError as exc:
        notes.append(str(exc))
    try:
        import winreg
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except (OSError, ImportError):
        pass
    if not erase:
        notes.append("Your data, settings and tokens were kept, so a reinstall picks up where you left off.")
    return notes


# --------------------------------------------------------------------------- Qt plumbing
class Worker(QThread):
    line = Signal(str)
    done = Signal(object)

    def __init__(self, fn: Callable[["Worker"], Any]) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            result = self._fn(self)
        except Exception as exc:
            import traceback
            log("ERROR " + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip())
            result = {"ok": False, "error": describe(exc)}
        self.done.emit(result)


def _label(text: str, name: str = "", wrap: bool = True) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(wrap)
    lbl.setOpenExternalLinks(True)
    if name:
        lbl.setObjectName(name)
    return lbl


class Page(QWizardPage):
    """A page whose Next can run slow work in the background first."""

    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__()
        self.layout_ = QVBoxLayout(self)
        self.layout_.setSpacing(10)
        self.layout_.addWidget(_label(title, "title"))
        if subtitle:
            self.layout_.addWidget(_label(subtitle, "muted"))
        self.status = _label("", "muted")
        self._passed = False
        self._worker: Worker | None = None

    @property
    def w(self) -> "SetupWizard":
        return self.wizard()  # type: ignore[return-value]

    def add(self, widget: QWidget) -> QWidget:
        self.layout_.addWidget(widget)
        return widget

    def finish_layout(self) -> None:
        self.layout_.addStretch(1)
        self.layout_.addWidget(self.status)

    def say(self, text: str, kind: str = "muted") -> None:
        self.status.setObjectName(kind)
        self.status.style().unpolish(self.status)  # re-apply the #ok/#err/#muted colour
        self.status.style().polish(self.status)
        if kind == "err":
            import html
            log_url = QUrl.fromLocalFile(str(SETUP_LOG)).toString()
            text = (f"{html.escape(text)}<br><a style='color:#7fd8ff' href='{log_url}'>Open the setup log</a> "
                    f"<span style='color:#9a9ab0'>(full details, to send if you need help: {SETUP_LOG})</span>")
            self.status.setTextFormat(Qt.RichText)
        else:
            self.status.setTextFormat(Qt.AutoText)
        self.status.setText(text)

    # subclasses: return None when there's nothing to do, else a background job
    def job(self) -> Callable[[Worker], dict[str, Any]] | None:
        return None

    def on_result(self, result: dict[str, Any]) -> bool:
        return bool(result.get("ok"))

    def busy_text(self) -> str:
        return "Working…"

    def initializePage(self) -> None:  # noqa: N802 -- Qt's own naming convention
        self._passed = False

    def validatePage(self) -> bool:  # noqa: N802
        if self._passed:
            return True
        job = self.job()
        if job is None:
            return True
        self.say(self.busy_text())
        self.w.set_busy(True)
        self._worker = Worker(job)
        self._worker.done.connect(self._done)
        self._worker.start()
        return False

    def _done(self, result: Any) -> None:
        self.w.set_busy(False)
        result = result if isinstance(result, dict) else {"ok": False, "error": str(result)}
        if self.on_result(result):
            self._passed = True
            if self.w.currentId() == self.w.pageIds()[-1]:
                self.w.accept()
            else:
                self.w.next()
        else:
            self.say(result.get("error") or "Something went wrong.", "err")


# --------------------------------------------------------------------------- pages
class WelcomePage(Page):
    def __init__(self) -> None:
        super().__init__("Welcome to myGeeKy",
                         "Your corner of GitHub, for research: the people, projects, papers and pulse of your field.")
        row = QHBoxLayout()
        icon = QLabel()
        if (ASSETS / "icon_128.png").exists():
            icon.setPixmap(QPixmap(str(ASSETS / "icon_128.png")))
        row.addWidget(icon)
        row.addWidget(_label("This wizard will:\n"
                             + ("  •  install or update myGeeKy (and Python, if you don't have it)\n" if WINDOWS
                                else "  •  check your myGeeKy install\n")
                             + "  •  connect your GitHub account\n"
                             + ("  •  optionally keep your data in a private GitHub repo (and install Git for it)\n"
                                if WINDOWS else "  •  optionally keep your data in a private GitHub repo\n")
                             + "  •  optionally turn on Signals (👋 📚 🤝 👀)\n"
                             + ("  •  add myGeeKy to your Start menu\n\n" if WINDOWS
                                else "  •  add myGeeKy to your applications menu\n\n")
                             + "myGeeKy only ever suggests. It never follows anyone for you."), 1)
        wrap = QWidget()
        wrap.setLayout(row)
        self.add(wrap)
        self.found = self.add(_label("Checking this computer…", "muted"))
        self.finish_layout()
        self._checked = False

    def initializePage(self) -> None:  # noqa: N802
        super().initializePage()
        if self._checked:
            return
        self.w.set_busy(True)
        worker = Worker(lambda wk: self.w.detect())
        worker.done.connect(self._detected)
        self._detector = worker
        worker.start()

    def _detected(self, info: Any) -> None:
        self._checked = True
        self.w.set_busy(False)
        self.found.setText(self.w.describe_install())


class InstallPage(Page):
    def __init__(self) -> None:
        super().__init__("Installing", "This takes a minute or two the first time.")
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.add(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.add(self.log)
        self.update_editable = QCheckBox("Replace my developer (editable) install with this version")
        self.update_editable.setVisible(False)
        self.add(self.update_editable)
        self.finish_layout()
        self._installed = False

    def initializePage(self) -> None:  # noqa: N802
        super().initializePage()
        self.update_editable.setVisible(bool(self.w.info.get("editable")))
        if not self._installed:
            self._start()

    def isComplete(self) -> bool:  # noqa: N802
        return self._installed

    def _start(self) -> None:
        self.progress.setRange(0, 0)
        self.w.set_busy(True)
        worker = Worker(self._install)
        worker.line.connect(self.log.appendPlainText)
        worker.done.connect(self._finished)
        self._job = worker
        worker.start()

    def _install(self, wk: Worker) -> dict[str, Any]:
        w = self.w
        if not w.python:
            w.python = install_python(wk.line.emit)
            if not w.python:
                return {"ok": False, "error": "Couldn't set up Python automatically. Install Python 3.12 from "
                                              "https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), "
                                              "then run this setup again."}
        wk.line.emit(f"Using Python: {w.python}")
        if not WINDOWS and not FROZEN:
            wk.line.emit("myGeeKy is installed in this Python, so there's nothing to download.")
        elif w.info.get("editable") and not self.update_editable.isChecked():
            wk.line.emit("Developer (editable) install found, so it was kept as is.")
        else:
            stopped = stop_running_panels()
            if stopped:
                wk.line.emit(f"Closed {stopped} open myGeeKy panel(s); they'll restart at the end.")
                w.restart_panel = True
            wheel = bundled_wheel()
            target = str(wheel) if wheel else "mygeeky"
            wk.line.emit(f"Installing {wheel.name if wheel else 'mygeeky from PyPI'}…")
            proc = _popen([w.python, "-m", "pip", "install", "--upgrade", "--disable-pip-version-check",
                                     target], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    creationflags=NO_WINDOW, encoding="utf-8", errors="replace")
            for line in proc.stdout:  # type: ignore[union-attr]
                line = line.rstrip()
                if line and not line.startswith("  "):
                    wk.line.emit(line)
            if proc.wait() != 0:
                return {"ok": False, "error": "pip couldn't install myGeeKy. See the log above."}
        wk.line.emit("Setting up Qt for the panel…")
        proc = _popen([w.python, "-m", "mygeeky.gui.bootstrap"], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, creationflags=NO_WINDOW,
                                encoding="utf-8", errors="replace")
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.rstrip()
            if line and not line.startswith("  "):
                wk.line.emit(line)
        if proc.wait() != 0:
            return {"ok": False, "error": "Couldn't set up Qt for the panel. See the log above."}
        status = api(w.python, "status")
        if not status.get("ok"):
            return status
        w.state = status
        wk.line.emit(f"myGeeKy {status.get('version')} is ready.")
        return {"ok": True}

    def _finished(self, result: Any) -> None:
        self.w.set_busy(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        if isinstance(result, dict) and result.get("ok"):
            self._installed = True
            self.say("Installed ✓", "ok")
        else:
            retry = QPushButton("Try again")
            retry.clicked.connect(lambda: (retry.deleteLater(), self._start()))
            self.add(retry)
            self.say((result or {}).get("error", "Install failed."), "err")
        self.completeChanged.emit()


class ProfilePage(Page):
    def __init__(self) -> None:
        super().__init__("About you", "myGeeKy matches people by your field, not just your languages. "
                                      "Only the username is required.")
        form = QFormLayout()
        form.setSpacing(8)
        self.username = QLineEdit()
        self.username.setPlaceholderText("your GitHub username")
        self.cv = QLineEdit()
        self.cv.setPlaceholderText("optional: .pdf, .txt or .md")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        cv_row = QHBoxLayout()
        cv_row.addWidget(self.cv, 1)
        cv_row.addWidget(browse)
        cv_wrap = QWidget()
        cv_wrap.setLayout(cv_row)
        self.orcid = QLineEdit()
        self.orcid.setPlaceholderText("optional, e.g. 0000-0002-1825-0097")
        self.scholar = QLineEdit()
        self.scholar.setPlaceholderText("optional: your Google Scholar profile URL")
        self.languages = QLineEdit()
        self.languages.setPlaceholderText("e.g. Python, R")
        self.topics = QLineEdit()
        self.topics.setPlaceholderText("e.g. gwas, single-cell, llm")
        form.addRow("GitHub username", self.username)
        form.addRow("CV", cv_wrap)
        form.addRow("ORCID iD", self.orcid)
        form.addRow("Google Scholar", self.scholar)
        form.addRow("Languages", self.languages)
        form.addRow("Topics", self.topics)
        box = QWidget()
        box.setLayout(form)
        self.add(box)
        self.finish_layout()
        self.registerField("username*", self.username)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Your CV", str(Path.home()), "CV (*.pdf *.txt *.md)")
        if path:
            self.cv.setText(path)

    def initializePage(self) -> None:  # noqa: N802
        super().initializePage()
        s = self.w.state
        if not self.username.text():
            self.username.setText(s.get("github_username", ""))
            self.cv.setText(s.get("cv_path", ""))
            self.orcid.setText(s.get("orcid_id", ""))
            self.scholar.setText(s.get("scholar_id", ""))
            self.languages.setText(", ".join(s.get("languages") or []))
            self.topics.setText(", ".join(s.get("topics") or []))

    def job(self):
        payload = {"github_username": self.username.text().strip(), "cv_path": self.cv.text().strip(),
                   "orcid_id": self.orcid.text().strip(), "scholar_id": self.scholar.text().strip(),
                   "languages": self.languages.text(), "topics": self.topics.text()}
        python = self.w.python
        return lambda wk: api(python, "save_profile", payload)

    def on_result(self, result):
        if result.get("ok"):
            self.w.refresh_state()
        return bool(result.get("ok"))


class TokenPage(Page):
    def __init__(self) -> None:
        super().__init__("Connect GitHub: token 1 of 2 (read-only)",
                         "myGeeKy reads public profiles, repos and followers, so this token is read-only "
                         "and can never follow anyone. Setup checks that: a token that can write to your "
                         "repos or follow people is refused here. (Signals, on a later page and optional, "
                         "uses a separate second token that can write to one repo only.)")
        # the easy way: sign in with GitHub (no token to create or copy)
        self.signin_card, signin_lay = _card("Easiest: sign in with GitHub")
        signin_lay.addWidget(_label("Click the button, type the code on the GitHub page that opens, and click "
                                    "Authorize. myGeeKy can then only read public data.", "muted"))
        row = QHBoxLayout()
        self.signin_btn = QPushButton("\U0001f511  Sign in with GitHub")
        self.signin_btn.setObjectName("primary")
        self.signin_btn.clicked.connect(self._sign_in)
        row.addWidget(self.signin_btn)
        row.addStretch(1)
        signin_lay.addLayout(row)
        self.code_row = QHBoxLayout()
        self.code_label = QLabel("")
        self.code_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.code_label.setStyleSheet("font-size:26px; font-weight:800; letter-spacing:4px; color:#ff6fd8;")
        self.copy_code = QPushButton("Copy code")
        self.copy_code.clicked.connect(lambda: QApplication.clipboard().setText(self.code_label.text()))
        self.copy_code.setVisible(False)
        self.code_row.addWidget(self.code_label)
        self.code_row.addWidget(self.copy_code)
        self.code_row.addStretch(1)
        signin_lay.addLayout(self.code_row)
        self.signin_status = _label("", "muted")
        signin_lay.addWidget(self.signin_status)
        self.add(self.signin_card)

        self.add(_label("Or use a token you make yourself:", "muted"))
        self.keep = QRadioButton("")
        self.paste = QRadioButton("Paste a read-only token")
        self.add(self.keep)
        self.add(self.paste)
        steps = _label(READ_TOKEN_STEPS, "muted")
        steps.setTextFormat(Qt.RichText)
        self.add(steps)
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.Password)
        self.token.setPlaceholderText("github_pat_…   (stored only in your " +
                                      ("Windows Credential Locker)" if WINDOWS else "system keyring)"))
        self.add(self.token)
        self.token.textChanged.connect(lambda: self.paste.setChecked(True))
        self.finish_layout()

    def initializePage(self) -> None:  # noqa: N802
        super().initializePage()
        source = self.w.state.get("token_source", "none")
        has = source != "none"
        self.keep.setVisible(has)
        self.keep.setText(f"Keep the token I already have, from your {source.split(' (')[0]}")
        (self.keep if has else self.paste).setChecked(True)

    def job(self):
        if self.keep.isChecked():
            return None
        token = self.token.text().strip()
        python = self.w.python
        return lambda wk: api(python, "store_token", {"token": token})

    # ---- Sign in with GitHub
    def _sign_in(self) -> None:
        self.signin_btn.setEnabled(False)
        self.signin_status.setText("Asking GitHub for a code\u2026")
        python = self.w.python

        def run(wk):
            flow = api(python, "github_login_start", timeout=60)
            if not flow.get("ok"):
                return flow
            wk.line.emit(json.dumps({"code": flow["user_code"], "uri": flow["verification_uri"]}))
            return api(python, "github_login_finish", {"device_code": flow["device_code"],
                                                        "interval": flow["interval"],
                                                        "expires_in": flow["expires_in"]},
                       timeout=flow["expires_in"] + 30)
        self._signin_worker = Worker(run)
        self._signin_worker.line.connect(self._show_code)
        self._signin_worker.done.connect(self._signed_in)
        self._signin_worker.start()

    def _show_code(self, payload: str) -> None:
        info = json.loads(payload)
        self.code_label.setText(info["code"])
        self.copy_code.setVisible(True)
        QApplication.clipboard().setText(info["code"])
        QDesktopServices.openUrl(QUrl(info["uri"]))
        self.signin_status.setText(f"Your browser opened {info['uri']}. The code is already copied: paste it "
                                   "there and click Authorize. Waiting for you\u2026")

    def _signed_in(self, result: Any) -> None:
        result = result if isinstance(result, dict) else {}
        self.signin_btn.setEnabled(True)
        self.copy_code.setVisible(False)
        self.code_label.setText("")
        if not result.get("ok"):
            self.signin_status.setText(result.get("error") or "The sign-in didn't finish. Try again.")
            return
        self.signin_status.setText(f"\u2713 Signed in as {result['login']}. Click Next.")
        if result.get("expiry"):
            self.w.notes.append(result["expiry"])
        self.w.refresh_state()
        self.keep.setVisible(True)
        self.keep.setText("Use my GitHub sign-in")
        self.keep.setChecked(True)
        self.signin_btn.setText("\u2713 Signed in")

    def on_result(self, result):
        if result.get("ok"):
            self.token.clear()  # don't keep it in memory longer than needed
            self.w.notes += result.get("notes") or []
            if result.get("expiry"):
                self.w.notes.append(result["expiry"])
            self.w.refresh_state()
        return bool(result.get("ok"))


class SyncPage(Page):
    def __init__(self) -> None:
        super().__init__("Your data, on every computer",
                         "Keep your settings, history and what the model learned in a PRIVATE GitHub "
                         "repo, so myGeeKy picks up where you left off on any machine.")
        self.enable = QCheckBox("Keep my data in a private GitHub repo")
        self.add(self.enable)
        self.repo = QLineEdit()
        self.add(self.repo)
        self.note = self.add(_label("", "muted"))
        self.steps = self.add(_label("", "muted"))
        self.steps.setTextFormat(Qt.RichText)
        self.steps.setOpenExternalLinks(True)
        self.finish_layout()

    def initializePage(self) -> None:  # noqa: N802
        super().initializePage()
        s = self.w.state
        self.repo.setText(s.get("sync_repo") or f"{s.get('github_username', 'you')}/mygeeky-data")
        already = bool(s.get("sync_repo") and s.get("sync_initialized"))
        self.note.setTextFormat(Qt.RichText)
        self._show_steps(already)
        self.repo.textChanged.connect(lambda: self._show_steps(already))
        # optional: on by default only where it can actually work
        self.enable.setChecked(already or bool(s.get("git") and s.get("gh")))
        if already:
            self.note.setText(f"✓ Already syncing with {s['sync_repo']}. Next re-connects and pulls the latest.")
        elif not s.get("git") and not WINDOWS:
            self.note.setText("<b>Optional.</b> Sync needs <b>Git</b>, which isn't installed yet. Install it with your "
                              "package manager (for example <code>sudo apt install git</code>), then come back to "
                              "this page. Everything else works without it.")
        elif not s.get("git"):
            self.note.setText("<b>Optional.</b> Sync needs <b>Git</b>, which isn't on this PC yet. Tick the box and "
                              "setup <b>installs Git for you</b> (just for you, no admin, a minute or two), then "
                              "sets up sync. Everything else works without it.")
        elif not s.get("gh"):
            self.note.setText("<b>Optional.</b> Your settings, CV text and history then follow you to every "
                              "computer you use myGeeKy on. Your tokens never go there.")
        else:
            self.note.setText("It's created as private if it doesn't exist. Tokens are never synced.")

    def _show_steps(self, already: bool) -> None:
        """Create the private repo first: myGeeKy can only do it for you when the GitHub CLI is signed in."""
        if already or self.w.state.get("gh"):
            self.steps.setText("")
            return
        from ..sync import new_repo_url
        repo = self.repo.text().strip() or "you/mygeeky-data"
        name = repo.split("/", 1)[-1]
        self.steps.setText(
            "<b>Before you click Next, create your private repo on GitHub:</b>"
            "<ol style='margin:2px 0 6px -20px'>"
            f"<li>Open <a {LINK} href='{new_repo_url(repo)}'>github.com → new repository ↗</a> "
            f"(the name <b>{name}</b> is filled in).</li>"
            "<li>Choose <b>Private</b>. Don't add a README, .gitignore or license: it must start empty.</li>"
            "<li>Click <b>Create repository</b>, then come back here and click Next.</li></ol>"
            "Only you can see it. myGeeKy writes your data there with your own Git login (the first time, Git "
            "asks you to sign in to GitHub in your browser); your read-only token is never used for it. "
            "A public repo is refused.")

    def job(self):
        if not self.enable.isChecked():
            return None
        repo = self.repo.text().strip()
        python = self.w.python
        needs_git = not self.w.state.get("git")

        def run(wk):
            if needs_git and not WINDOWS:
                if not find_git():
                    return {"ok": False, "error": "Sync needs Git: install it (e.g. `sudo apt install git`) and click "
                                                  "Next again, or untick this to skip sync."}
            elif needs_git:
                git = find_git() or install_git(lambda m: log(m))
                if not git:
                    return {"ok": False, "error": "Git couldn't be installed. Untick this to skip sync, or install "
                                                  "Git from https://git-scm.com/download/win and run setup again."}
                put_on_path(git)
            return api(python, "sync_init", {"repo": repo}, timeout=900)
        return run

    def busy_text(self) -> str:
        if not self.w.state.get("git"):
            return "Installing Git, then setting up sync (a minute or two)…"
        return "Setting up sync…"

    def on_result(self, result):
        if result.get("ok"):
            self.w.notes.append(result.get("message", ""))
            self.w.refresh_state()
        return bool(result.get("ok"))


LINK = 'style="color:#7fd8ff"'

READ_TOKEN_STEPS = (
    "<b>To create token 1 (read-only):</b><ol style='margin:2px 0 0 -20px'>"
    f"<li>Open <a {LINK} href='{READ_TOKEN_URL}'>github.com → new fine-grained token ↗</a>. "
    "Name it <b>mygeeky</b>. <b>Expiration:</b> pick a long one (90 days or a year); myGeeKy reminds "
    "you a week before it ends.</li>"
    "<li><b>Repository access</b> → choose <b>Public repositories</b>.</li>"
    "<li>Under <i>Account</i>, click <b>Add permissions</b> (on older pages: open <b>Account permissions</b>), "
    "pick <b>Followers</b> and set it to <b>Read-only</b>.</li>"
    "<li>Don't add anything else. Click <b>Generate token</b>, copy it and paste it below.</li></ol>")


NEW_BEACON_REPO_URL = ("https://github.com/new?name=mygeeky-beacon&visibility=public"
                       "&description=My+myGeeKy+beacon+(non-verbal+signals)")
OL = "<ol style='margin:2px 0 6px -20px'>"


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("stepCard")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(14, 10, 14, 12)
    lay.setSpacing(6)
    head = QLabel(title)
    head.setObjectName("stepTitle")
    lay.addWidget(head)
    return card, lay


class SignalsPage(Page):
    """Two steps, in an order GitHub forces: the repo must exist before a token
    can be limited to it. Step 2 stays locked until Step 1 is verified on GitHub."""

    def __init__(self) -> None:
        super().__init__("Signals (optional)",
                         "Send other myGeeKy users small private signals (🙏 thanks · 📚 learned from "
                         "your work · 👀 following your work · 🤝 collaborate) and see theirs. Only the "
                         "person you send one to can read it, and no reply is ever expected.")
        self._stage = "none"            # none | partial | live | checking
        self.enable = QCheckBox("Join Signals. My beacon (status, interests) is public; my signals are private.")
        self.add(self.enable)
        self.summary = _label("", "muted")
        self.summary.setTextFormat(Qt.RichText)
        self.add(self.summary)

        # Step 1: the public repo
        self.step1, lay1 = _card("Step 1 · Create your public beacon repo on GitHub")
        self.step1_text = _label("", "muted")
        self.step1_text.setTextFormat(Qt.RichText)
        lay1.addWidget(self.step1_text)
        self.step1_status = _label("")
        lay1.addWidget(self.step1_status)
        row1 = QHBoxLayout()
        self.open_repo = QPushButton("Open github.com/new ↗")
        self.open_repo.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(NEW_BEACON_REPO_URL)))
        self.create_repo = QPushButton("Create it for me")
        self.create_repo.clicked.connect(self._create_repo)
        self.check_repo = QPushButton("I've created it: check ✓")
        self.check_repo.clicked.connect(self._recheck)
        for b in (self.open_repo, self.create_repo, self.check_repo):
            row1.addWidget(b)
        row1.addStretch(1)
        lay1.addLayout(row1)
        self.add(self.step1)

        # Step 2: a second token, for that repo only
        self.step2, lay2 = _card("Step 2 · Create token 2 of 2: write access to that repo only")
        self.step2_text = _label("", "muted")
        self.step2_text.setTextFormat(Qt.RichText)
        lay2.addWidget(self.step2_text)
        row2 = QHBoxLayout()
        self.open_token = QPushButton("Open token page ↗")
        self.open_token.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(READ_TOKEN_URL)))
        row2.addWidget(self.open_token)
        row2.addStretch(1)
        lay2.addLayout(row2)
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.Password)
        self.token.setPlaceholderText("Token 2 (github_pat_…), then click Next")
        lay2.addWidget(self.token)
        self.add(self.step2)

        self.enable.toggled.connect(lambda on: self._render())
        self.finish_layout()

    # ---- state -> widgets
    def _render(self) -> None:
        s = self.w.state
        user = s.get("github_username", "you")
        on = self.enable.isChecked()
        stage = self._stage
        repo_exists = stage in ("partial", "live")
        done = stage == "live" and s.get("beacon_enabled") and s.get("beacon_token")
        self.step1.setVisible(on and not done)
        self.step2.setVisible(on and not done)
        if stage == "checking":
            self.step1_status.setText("Checking GitHub…")
        elif repo_exists:
            self.step1_status.setText(f"✓ {user}/mygeeky-beacon exists and is public. Step 1 is done.")
        else:
            self.step1_status.setText(f"✗ {user}/mygeeky-beacon doesn't exist yet.")
        self.step1_status.setObjectName("ok" if repo_exists else "muted")
        self.step1_status.style().unpolish(self.step1_status)
        self.step1_status.style().polish(self.step1_status)
        self.step1_text.setText(
            f"Click <b>Open github.com/new</b>: the name <b>mygeeky-beacon</b> and <b>Public</b> are filled "
            f"in. Check the owner is <b>{user}</b>, click <b>Create repository</b>, and leave it empty. "
            "Then come back and click <b>I've created it</b>.")
        for b in (self.open_repo, self.check_repo):
            b.setVisible(not repo_exists)
        self.create_repo.setVisible(not repo_exists and bool(s.get("gh")))
        self.check_repo.setEnabled(stage != "checking")

        self.step2.setEnabled(repo_exists)
        self.step2_text.setText(
            ("<i>Finish Step 1 first: GitHub only lets a token be limited to a repo that already exists.</i><br>"
             if not repo_exists else "") +
            "This is a <b>second</b> token, separate from your read-only one. "
            f"Name it <b>mygeeky-beacon</b>, owner <b>{user}</b>, a long <b>Expiration</b> "
            "(myGeeKy reminds you a week before it ends), then:" + OL +
            "<li><b>Repository access</b> → <b>Only select repositories</b> → pick <b>mygeeky-beacon</b>.</li>"
            "<li><b>Add permissions</b> (under <i>Repositories</i>) → <b>Contents</b> → <b>Read and write</b>. "
            "<i>Metadata: Read-only</i> is added by itself.</li>"
            "<li>Nothing else. <b>Generate token</b>, copy it, paste it below. Setup checks it can write "
            "to mygeeky-beacon (and warns if it can write anywhere else), then publishes your beacon.</li></ol>"
            "<i>Don't paste token 1 here: it's read-only, so it can't publish.</i>")
        if s.get("beacon_token"):
            self.token.setPlaceholderText("Leave empty to use the token already saved, or paste a new one")

    def initializePage(self) -> None:  # noqa: N802
        super().initializePage()
        self.enable.setChecked(bool(self.w.state.get("beacon_enabled")))
        self._recheck()

    def _recheck(self) -> None:
        self._stage = "checking"
        self.summary.setText("Checking your Signals setup on GitHub…")
        self._render()
        python = self.w.python
        self._checker = Worker(lambda wk: api(python, "beacon_check", timeout=60))
        self._checker.done.connect(self._checked)
        self._checker.start()

    def _create_repo(self) -> None:
        self.create_repo.setEnabled(False)
        self.step1_status.setText("Creating it with the GitHub CLI…")
        python = self.w.python
        self._creator = Worker(lambda wk: api(python, "beacon_create_repo", timeout=120))
        self._creator.done.connect(lambda r: (self.create_repo.setEnabled(True),
                                              self.say(r.get("error"), "err") if not r.get("ok") else None,
                                              self._recheck()))
        self._creator.start()

    def _checked(self, result: Any) -> None:
        """Tick the box for anyone who already has a beacon on GitHub (from
        another computer, or a setup that stopped halfway), and say where
        they stand. A brand-new user stays unticked: joining makes signals
        public, so it must be their own choice."""
        s = self.w.state
        user = s.get("github_username", "you")
        result = result if isinstance(result, dict) else {}
        self._stage = result.get("stage", "none") if result.get("ok") else "none"
        repo_link = f"<a {LINK} href='https://github.com/{user}/mygeeky-beacon'>{user}/mygeeky-beacon ↗</a>"
        if self._stage == "live":
            self.enable.setChecked(True)
            if s.get("beacon_enabled") and s.get("beacon_token"):
                self.summary.setText(f"<b>✓ You're on Signals:</b> {repo_link}. Nothing to do here.")
            else:
                self.summary.setText(f"<b>Your beacon is live</b> ({repo_link}). To send signals from this "
                                     "computer, paste a token made with Step 2.")
        elif self._stage == "partial":
            self.enable.setChecked(True)
            missing = [msg for ok, msg in result.get("results") or [] if not ok]
            self.summary.setText(f"<b>Your Signals setup isn't finished yet</b> ({repo_link}). "
                                 + (f"Still missing: {missing[-1]}" if missing else ""))
        else:
            self.summary.setText("It takes two steps on github.com, in this order. Setup checks each one.")
        self._render()

    # ---- Next
    def job(self):
        s = self.w.state
        if not self.enable.isChecked():
            return None
        if self._stage == "live" and s.get("beacon_enabled") and s.get("beacon_token"):
            return None
        if self._stage not in ("partial", "live"):
            return lambda wk: {"ok": False, "error": "Do Step 1 first: create the mygeeky-beacon repo on GitHub, "
                                                     "then click \"I've created it\". Or untick Join Signals."}
        token = self.token.text().strip()
        if not token and not s.get("beacon_token"):
            return lambda wk: {"ok": False, "error": "Paste token 2 (Step 2) first, or untick Join Signals."}
        python = self.w.python
        return lambda wk: api(python, "beacon_init", {"token": token})

    def on_result(self, result):
        if result.get("ok"):
            self.token.clear()
            self.w.notes += result.get("notes") or []
            self.w.notes.append(f"Your beacon is live: {result.get('url')}")
            self.w.refresh_state()
        return bool(result.get("ok"))


class FinishPage(Page):
    def __init__(self) -> None:
        super().__init__("Almost done", "Pick what you'd like, then click Finish.")
        self.start_menu = self.add(QCheckBox("Add myGeeKy to the Start menu" if WINDOWS
                                             else "Add myGeeKy to the applications menu"))
        self.desktop = self.add(QCheckBox("Add a desktop shortcut"))
        self.desktop.setVisible(WINDOWS)
        self.startup = self.add(QCheckBox("Open the panel when I sign in to Windows" if WINDOWS
                                          else "Open the panel when I log in"))
        self.weekly = self.add(QCheckBox("Refresh suggestions every Monday at 09:00 (scheduled task)" if WINDOWS
                                         else "Refresh suggestions every Monday at 09:00 (cron)"))
        self.launch = self.add(QCheckBox("Open the myGeeKy panel now"))
        for box in (self.start_menu, self.startup, self.launch):
            box.setChecked(True)
        self.summary = self.add(_label("", "muted"))
        self.finish_layout()

    def initializePage(self) -> None:  # noqa: N802
        super().initializePage()
        if WINDOWS:
            paths = shortcut_paths()
            self.desktop.setChecked(paths["desktop"].exists())
            self.startup.setChecked(paths["startup"].exists() or not self.w.state.get("configured"))
        else:
            from . import desktop
            self.startup.setChecked(desktop.autostart_path().exists() or not self.w.state.get("configured"))
        self.summary.setText("\n".join(n for n in self.w.notes if n))

    def job(self):
        choices = {k: getattr(self, k).isChecked() for k in ("start_menu", "desktop", "startup", "weekly", "launch")}
        w = self.w
        return lambda wk: w.apply_finish(choices)


class SetupWizard(QWizard):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("myGeeKy Setup")
        if (ASSETS / "icon_64.png").exists():
            self.setWindowIcon(QIcon(str(ASSETS / "icon_64.png")))
        self.setWizardStyle(QWizard.ModernStyle)
        self.setOption(QWizard.NoBackButtonOnStartPage, True)
        self.setOption(QWizard.NoCancelButtonOnLastPage, True)
        self.setMinimumSize(700, 620)
        self.button(QWizard.NextButton).setObjectName("primary")
        self.button(QWizard.FinishButton).setObjectName("primary")
        self.setStyleSheet(STYLE)
        self.python: str | None = None
        self.info: dict[str, Any] = {}
        self.state: dict[str, Any] = {}
        self.notes: list[str] = []
        self.restart_panel = False
        for page in (WelcomePage(), InstallPage(), ProfilePage(), TokenPage(), SyncPage(), SignalsPage(),
                     FinishPage()):
            self.addPage(page)
        self.resize(700, 620)

    # ---- environment
    def detect(self) -> dict[str, Any]:
        self.python = find_python()
        self.info = installed_info(self.python) if self.python else {"version": None, "editable": False}
        return self.info

    def describe_install(self) -> str:
        new = wheel_version(bundled_wheel()) or "the latest version"
        have = self.info.get("version")
        if not self.python:
            return "No Python found. Setup will install Python 3.12 for you first."
        if not WINDOWS and not FROZEN and have:
            return (f"Found myGeeKy {have}. Setup connects your GitHub account and keeps all your settings. "
                    "(To update myGeeKy later, run the install line again.)")
        if self.info.get("editable"):
            return f"Found your developer install ({have}). Setup keeps it unless you choose otherwise."
        if have:
            return f"Found myGeeKy {have}. Setup will update it to {new} and keep all your settings."
        return f"Setup will install myGeeKy {new}."

    def refresh_state(self) -> None:
        status = api(self.python, "status") if self.python else {}
        if status.get("ok"):
            self.state = status

    def set_busy(self, busy: bool) -> None:
        for which in (QWizard.NextButton, QWizard.BackButton, QWizard.FinishButton, QWizard.CancelButton):
            self.button(which).setEnabled(not busy)
        if not busy:
            page = self.currentPage()
            self.button(QWizard.NextButton).setEnabled(page.isComplete() if page else True)

    # ---- the Finish page's work (runs in a Worker)
    def apply_finish(self, choices: dict[str, bool]) -> dict[str, Any]:
        if not WINDOWS:
            return self._apply_finish_elsewhere(choices)
        python = self.python or sys.executable
        pythonw = pythonw_for(python)
        pkg = package_dir(python)
        icon = str(Path(pkg) / "assets" / "icon.ico") if pkg and (Path(pkg) / "assets" / "icon.ico").exists() else None
        paths = shortcut_paths()
        problems = []
        names = {"start_menu": "Start menu", "desktop": "desktop", "startup": "sign-in"}
        for key in ("start_menu", "desktop", "startup"):
            if choices[key]:
                if not make_shortcut(paths[key], pythonw, "-m mygeeky.gui.app", icon):
                    problems.append(f"Couldn't create the {names[key]} shortcut.")
            elif paths[key].exists() and key != "start_menu":
                paths[key].unlink()
        if choices["weekly"]:
            result = api(python, "schedule")
            if not result.get("ok"):
                problems.append(f"Couldn't set up the weekly run: {result.get('error') or result.get('message')}")
        try:
            register_uninstaller(python, self.state.get("version", ""), icon)
        except OSError as exc:
            log(f"ERROR couldn't add myGeeKy to Installed apps: {exc}")
        if problems:
            return {"ok": False, "error": " ".join(problems) + " Untick it and click Finish again, or open "
                                          "myGeeKy any time with `mygeeky gui`."}
        if choices["launch"] or self.restart_panel:
            _popen([pythonw, "-m", "mygeeky.gui.app"], creationflags=NO_WINDOW,
                   close_fds=True, cwd=str(Path.home()))
        return {"ok": True}

    def _apply_finish_elsewhere(self, choices: dict[str, bool]) -> dict[str, Any]:
        """Linux and macOS: the applications menu (and login) entry, cron, and the panel."""
        from . import desktop
        python = self.python or sys.executable
        problems = []
        try:
            if choices["start_menu"] or choices["startup"]:
                desktop.install_menu_entry(autostart=choices["startup"])
            elif desktop.autostart_path().exists():
                desktop.autostart_path().unlink()
        except OSError as exc:
            problems.append(f"Couldn't add myGeeKy to the applications menu ({exc}).")
        if choices["weekly"]:
            result = api(python, "schedule")
            if not result.get("ok"):
                problems.append(f"Couldn't set up the weekly run: {result.get('error') or result.get('message')}")
        if problems:
            return {"ok": False, "error": " ".join(problems) + " Untick it and click Finish again, or open "
                                          "myGeeKy any time with `mygeeky gui`."}
        if choices["launch"] or self.restart_panel:
            winproc.popen([python, "-m", "mygeeky.gui.app"], cwd=str(Path.home()), close_fds=True,
                          start_new_session=True, stdin=subprocess.DEVNULL,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ok": True}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--selftest" in argv:  # used by installer/build.py: is the payload really inside?
        wheel = bundled_wheel()
        Path(argv[argv.index("--selftest") + 1]).write_text(json.dumps({
            "frozen": FROZEN, "wheel": wheel.name if wheel else None,
            "icon": (ASSETS / "icon_128.png").exists(),
            "errors": describe(FileNotFoundError(2, "x", "probe.txt")),
            "ssl": __import__("ssl").OPENSSL_VERSION}), encoding="utf-8")
        return 0
    app = QApplication.instance() or QApplication([])
    app.setFont(QFont("Segoe UI", 10))
    if "--uninstall" in argv:            # Windows' Apps list: the step-by-step uninstall wizard
        from .uninstall_wizard import main as uninstall_main
        return uninstall_main()
    import platform
    log(f"=== myGeeKy setup started (bundled wheel: {wheel_version(bundled_wheel()) or 'none'}, "
        f"frozen: {FROZEN}, {platform.platform()})")
    wizard = SetupWizard()
    wizard.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
