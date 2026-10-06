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
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FROZEN = getattr(sys, "frozen", False)
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
QProgressBar { background: #1f1f2c; border: none; border-radius: 4px; height: 8px; }
QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #ff6fd8, stop:1 #7a5cff);
    border-radius: 4px; }
"""


# --------------------------------------------------------------------------- environment (no Qt)
def _run(cmd: list[str], stdin: str | None = None, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout,
                          creationflags=NO_WINDOW, encoding="utf-8", errors="replace")


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
        v = python_version(exe)
        if v and v >= MIN_PY:
            return exe
    return None


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
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "That step took too long."}
    for line in reversed(r.stdout.strip().splitlines()):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return {"ok": False, "error": (r.stderr or r.stdout).strip()[-400:] or "No answer from myGeeKy."}


def stop_running_panels() -> int:
    """Close open myGeeKy panels so they restart on the new version."""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
          "Where-Object { $_.CommandLine -match 'mygeeky\\.gui' -and $_.CommandLine -notmatch 'setup_wizard' } | "
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
        return subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, capture_output=True,
                              creationflags=NO_WINDOW, timeout=60).returncode == 0
    except Exception:
        return False


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


def uninstall(python: str) -> list[str]:
    """Remove shortcuts, the weekly task, the package and the Apps entry.
    Your data and tokens stay, so a reinstall picks up where you left off."""
    notes = []
    stop_running_panels()
    for p in shortcut_paths().values():
        if p.exists():
            p.unlink()
    _run(["schtasks", "/Delete", "/TN", "myGeeKyWeeklyRun", "/F"], timeout=60)
    r = _run([python, "-m", "pip", "uninstall", "-y", "mygeeky"], timeout=300)
    notes.append("Removed the myGeeKy package." if r.returncode == 0 else "pip couldn't remove the package.")
    try:
        import winreg
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass
    notes.append("Your data, settings and tokens were kept.")
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
            result = {"ok": False, "error": str(exc)}
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
        self.status.setText(text)

    # subclasses: return None when there's nothing to do, else a background job
    def job(self) -> Callable[[Worker], dict[str, Any]] | None:
        return None

    def on_result(self, result: dict[str, Any]) -> bool:
        return bool(result.get("ok"))

    def initializePage(self) -> None:  # noqa: N802 -- Qt's own naming convention
        self._passed = False

    def validatePage(self) -> bool:  # noqa: N802
        if self._passed:
            return True
        job = self.job()
        if job is None:
            return True
        self.say("Working…")
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
                         "Find GitHub people who share your research, and will actually follow you back.")
        row = QHBoxLayout()
        icon = QLabel()
        if (ASSETS / "icon_128.png").exists():
            icon.setPixmap(QPixmap(str(ASSETS / "icon_128.png")))
        row.addWidget(icon)
        row.addWidget(_label("This wizard will:\n"
                             "  •  install or update myGeeKy\n"
                             "  •  connect your GitHub account\n"
                             "  •  optionally keep your data in a private GitHub repo\n"
                             "  •  optionally turn on Signals (👋 📚 🤝 👀)\n"
                             "  •  add myGeeKy to your Start menu\n\n"
                             "myGeeKy only ever suggests. It never follows anyone for you."), 1)
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
            wk.line.emit("No Python 3.9+ found. Installing Python 3.12 for you (winget, just for you)…")
            r = _run(["winget", "install", "-e", "--id", "Python.Python.3.12", "--scope", "user", "--silent",
                      "--accept-package-agreements", "--accept-source-agreements"], timeout=1200)
            wk.line.emit(r.stdout[-600:])
            w.python = find_python()
            if not w.python:
                return {"ok": False, "error": "Couldn't install Python. Install it from python.org, then run "
                                              "this setup again."}
        wk.line.emit(f"Using Python: {w.python}")
        if w.info.get("editable") and not self.update_editable.isChecked():
            wk.line.emit("Developer (editable) install found, so it was kept as is.")
        else:
            stopped = stop_running_panels()
            if stopped:
                wk.line.emit(f"Closed {stopped} open myGeeKy panel(s); they'll restart at the end.")
                w.restart_panel = True
            wheel = bundled_wheel()
            target = f"{wheel}[gui,pdf]" if wheel else "mygeeky[gui,pdf]"
            wk.line.emit(f"Installing {wheel.name if wheel else 'mygeeky from PyPI'}…")
            proc = subprocess.Popen([w.python, "-m", "pip", "install", "--upgrade", "--disable-pip-version-check",
                                     target], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    creationflags=NO_WINDOW, encoding="utf-8", errors="replace")
            for line in proc.stdout:  # type: ignore[union-attr]
                line = line.rstrip()
                if line and not line.startswith("  "):
                    wk.line.emit(line)
            if proc.wait() != 0:
                return {"ok": False, "error": "pip couldn't install myGeeKy. See the log above."}
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
        super().__init__("Connect GitHub",
                         "myGeeKy reads public profiles, repos and followers. It needs a token with "
                         "read access only, and never anything that could follow someone.")
        self.keep = QRadioButton("")
        self.paste = QRadioButton("Paste a read-only token")
        self.add(self.keep)
        self.add(self.paste)
        steps = _label(READ_TOKEN_STEPS, "muted")
        steps.setTextFormat(Qt.RichText)
        self.add(steps)
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.Password)
        self.token.setPlaceholderText("github_pat_…   (stored only in your Windows Credential Locker)")
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

    def on_result(self, result):
        if result.get("ok"):
            self.token.clear()  # don't keep it in memory longer than needed
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
        self.finish_layout()

    def initializePage(self) -> None:  # noqa: N802
        super().initializePage()
        s = self.w.state
        self.repo.setText(s.get("sync_repo") or f"{s.get('github_username', 'you')}/mygeeky-data")
        already = bool(s.get("sync_repo") and s.get("sync_initialized"))
        self.enable.setChecked(True)
        if already:
            self.note.setText(f"✓ Already syncing with {s['sync_repo']}. Next re-connects and pulls the latest.")
        elif not s.get("gh"):
            self.note.setText("Creating a new repo needs the GitHub CLI (`gh`, from cli.github.com, then "
                              "`gh auth login`). An existing private repo works with your usual git login.")
        else:
            self.note.setText("It's created as private if it doesn't exist. Tokens are never synced.")

    def job(self):
        if not self.enable.isChecked():
            return None
        repo = self.repo.text().strip()
        python = self.w.python
        return lambda wk: api(python, "sync_init", {"repo": repo}, timeout=900)

    def on_result(self, result):
        if result.get("ok"):
            self.w.notes.append(result.get("message", ""))
            self.w.refresh_state()
        return bool(result.get("ok"))


LINK = 'style="color:#7fd8ff"'

READ_TOKEN_STEPS = (
    "<b>To create a read-only token:</b><ol style='margin:2px 0 0 -20px'>"
    f"<li>Open <a {LINK} href='{READ_TOKEN_URL}'>github.com → new fine-grained token ↗</a>. "
    "Name it <b>mygeeky</b>.</li>"
    "<li><b>Repository access</b> → choose <b>Public repositories</b>.</li>"
    "<li>Under <i>Account</i>, click <b>Add permissions</b> (on older pages: open <b>Account permissions</b>), "
    "pick <b>Followers</b> and set it to <b>Read-only</b>.</li>"
    "<li>Don't add anything else. Click <b>Generate token</b>, copy it and paste it below.</li></ol>")


def beacon_steps(user: str, has_gh: bool) -> str:
    new_repo = ("https://github.com/new?name=mygeeky-beacon&visibility=public"
                "&description=My+myGeeKy+beacon+(non-verbal+signals)")
    repo_step = (
        f"<li>Setup creates the public repo <b>{user}/mygeeky-beacon</b> for you.</li>" if has_gh else
        f"<li><b>Create the repo:</b> open <a {LINK} href='{new_repo}'>github.com/new ↗</a> "
        "(the name <b>mygeeky-beacon</b> and <b>Public</b> are filled in), click <b>Create repository</b>. "
        "Then click the ⚙ next to <b>About</b> on the repo page, add the topic <b>mygeeky-beacon</b> "
        "and save, so other users can find you.</li>")
    return (
        f"Your signals live in a public repo, <b>{user}/mygeeky-beacon</b>, written with a token that can "
        "touch only that repo.<ol style='margin:2px 0 0 -20px'>"
        + repo_step +
        f"<li><b>Create the token:</b> open <a {LINK} href='{READ_TOKEN_URL}'>new fine-grained token ↗</a>. "
        f"Name it <b>mygeeky-beacon</b>, owner <b>{user}</b>.</li>"
        "<li><b>Repository access</b> → <b>Only select repositories</b> → pick <b>mygeeky-beacon</b>. "
        "(The permissions only appear once a repo is picked, so the repo must exist first.)</li>"
        "<li>Under <i>Repositories</i>, click <b>Add permissions</b> and pick <b>Contents</b> "
        "(on older pages: open <b>Repository permissions</b> and find <b>Contents</b> in the list). "
        "Set it to <b>Read and write</b>. <i>Metadata: Read-only</i> gets added by itself, which is fine.</li>"
        "<li>Don't add anything else. Click <b>Generate token</b>, copy it and paste it below.</li></ol>")


class SignalsPage(Page):
    def __init__(self) -> None:
        super().__init__("Signals (optional)",
                         "Send other myGeeKy users emoji signals (👋 wave · 📚 learn from you · "
                         "🤝 collaborate · 👀 following your work) and see theirs. No text, ever.")
        self.enable = QCheckBox("Join Signals. I understand my signals are public.")
        self.add(self.enable)
        self.steps = _label("", "muted")
        self.steps.setTextFormat(Qt.RichText)
        self.add(self.steps)
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.Password)
        self.token.setPlaceholderText("beacon token (github_pat_…)")
        self.add(self.token)
        self.enable.toggled.connect(self._toggle)
        self.finish_layout()

    def _toggle(self, on: bool) -> None:
        self.steps.setVisible(on)
        self.token.setVisible(on and not self.w.state.get("beacon_token"))

    def initializePage(self) -> None:  # noqa: N802
        super().initializePage()
        s = self.w.state
        user = s.get("github_username", "you")
        if s.get("beacon_enabled"):
            self.steps.setText(f"✓ You're already on Signals: <a {LINK} href='https://github.com/{user}/"
                               f"mygeeky-beacon'>{user}/mygeeky-beacon ↗</a>. Untick to leave it as it is; "
                               "nothing changes either way.")
        else:
            self.steps.setText(beacon_steps(user, has_gh=bool(s.get("gh"))))
        self.enable.setChecked(bool(s.get("beacon_enabled")))
        self._toggle(self.enable.isChecked())

    def job(self):
        s = self.w.state
        if not self.enable.isChecked() or s.get("beacon_enabled"):
            return None
        token = self.token.text().strip()
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
        self.start_menu = self.add(QCheckBox("Add myGeeKy to the Start menu"))
        self.desktop = self.add(QCheckBox("Add a desktop shortcut"))
        self.startup = self.add(QCheckBox("Open the panel when I sign in to Windows"))
        self.weekly = self.add(QCheckBox("Refresh suggestions every Monday at 09:00 (scheduled task)"))
        self.launch = self.add(QCheckBox("Open the myGeeKy panel now"))
        for box in (self.start_menu, self.startup, self.launch):
            box.setChecked(True)
        self.summary = self.add(_label("", "muted"))
        self.finish_layout()

    def initializePage(self) -> None:  # noqa: N802
        super().initializePage()
        paths = shortcut_paths()
        self.desktop.setChecked(paths["desktop"].exists())
        self.startup.setChecked(paths["startup"].exists() or not self.w.state.get("configured"))
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
        python = self.python or sys.executable
        pythonw = pythonw_for(python)
        pkg = package_dir(python)
        icon = str(Path(pkg) / "assets" / "icon.ico") if pkg and (Path(pkg) / "assets" / "icon.ico").exists() else None
        paths = shortcut_paths()
        for key in ("start_menu", "desktop", "startup"):
            if choices[key]:
                make_shortcut(paths[key], pythonw, "-m mygeeky.gui.app", icon)
            elif paths[key].exists() and key != "start_menu":
                paths[key].unlink()
        if choices["weekly"]:
            api(python, "schedule")
        try:
            register_uninstaller(python, self.state.get("version", ""), icon)
        except OSError:
            pass
        if choices["launch"] or self.restart_panel:
            subprocess.Popen([pythonw, "-m", "mygeeky.gui.app"], creationflags=NO_WINDOW,
                             close_fds=True, cwd=str(Path.home()))
        return {"ok": True}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--selftest" in argv:  # used by installer/build.py: is the payload really inside?
        wheel = bundled_wheel()
        Path(argv[argv.index("--selftest") + 1]).write_text(json.dumps({
            "frozen": FROZEN, "wheel": wheel.name if wheel else None,
            "icon": (ASSETS / "icon_128.png").exists()}), encoding="utf-8")
        return 0
    app = QApplication.instance() or QApplication([])
    app.setFont(QFont("Segoe UI", 10))
    if "--uninstall" in argv:
        from PySide6.QtWidgets import QMessageBox
        python = sys.executable if not FROZEN else (find_python() or "")
        if QMessageBox.question(None, "Uninstall myGeeKy",
                                "Remove myGeeKy from this computer?\n\nYour data, settings and tokens are kept, "
                                "so a reinstall picks up where you left off.") != QMessageBox.Yes:
            return 1
        QMessageBox.information(None, "myGeeKy", "\n".join(uninstall(python)))
        return 0
    wizard = SetupWizard()
    wizard.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
