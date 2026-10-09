"""Uninstall myGeeKy, step by step, so you know exactly what happens.

    pythonw -m mygeeky.gui.uninstall_wizard      (⚙ -> Uninstall..., or Windows' Apps list)

1. What uninstalling means.
2. Choose what to remove, each part explained: the program (always), your data
   on this computer, your saved tokens and Signals key, your Signals beacon on
   GitHub (withdrawn), and the GitHub pages to delete your repos yourself.
3. A summary of exactly what will happen and what stays; anything that can't
   be undone needs "I understand" ticked before Uninstall is enabled.
4. Each step as it runs, and what it did.

Order matters: the beacon is withdrawn first (it needs your Signals token),
then the tokens and data go, and the program last (everything else needs it).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (QApplication, QCheckBox, QFrame, QScrollArea, QVBoxLayout, QWidget, QWizard,
                               QWizardPage)

from .. import auth
from ..config import DATA_DIR, load_config
from .setup_wizard import STYLE, Worker, _label, find_python, uninstall

FROZEN = getattr(sys, "frozen", False)


def _size(path: Path) -> str:
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
    except OSError:
        pass
    return f"{total / 1e6:.1f} MB" if total >= 1e5 else f"{total / 1e3:.0f} KB"


def inventory() -> dict[str, Any]:
    """What myGeeKy has on this computer and on GitHub, for the choices."""
    from .. import uninstall as un
    try:
        cfg = load_config()
    except Exception:
        cfg = None
    user = cfg.github_username if cfg else ""
    tokens = 0
    try:
        import keyring
        tokens = sum(1 for s in un.KEYRING_SERVICES if user and keyring.get_password(s, user) is not None)
    except Exception:
        pass
    return {
        "user": user,
        "data": DATA_DIR.exists(), "data_path": str(DATA_DIR), "data_size": _size(DATA_DIR) if DATA_DIR.exists() else "",
        "tokens": tokens,
        "beacon": bool(cfg and cfg.beacon_enabled), "beacon_token": bool(user and auth.get_beacon_token(user)),
        "sync": cfg.sync_repo if cfg else "",
    }


class Page(QWizardPage):
    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__()
        self.lay = QVBoxLayout(self)
        self.lay.setSpacing(10)
        self.lay.addWidget(_label(title, "title"))
        if subtitle:
            self.lay.addWidget(_label(subtitle, "muted"))

    @property
    def w(self) -> "UninstallWizard":
        return self.wizard()  # type: ignore[return-value]


class IntroPage(Page):
    def __init__(self, inv: dict[str, Any]) -> None:
        super().__init__("Uninstall myGeeKy",
                         "This removes myGeeKy from this computer. On the next page you choose, item by item, "
                         "whether to also remove your data, your saved tokens and your Signals beacon. Nothing is "
                         "removed until you confirm on the page after that.")
        found = [f"<b>The program</b> (myGeeKy for {inv['user'] or 'this computer'})"]
        if inv["data"]:
            found.append(f"<b>Your data</b>: {inv['data_size']} in <code>{inv['data_path']}</code>")
        if inv["tokens"]:
            found.append(f"<b>{inv['tokens']} saved token{'s' if inv['tokens'] != 1 else ''} or keys</b> in your system keyring")
        if inv["beacon"]:
            found.append(f"<b>Your Signals beacon</b>: the public repo <code>{inv['user']}/mygeeky-beacon</code>")
        if inv["sync"]:
            found.append(f"<b>Your sync repo</b>: the private repo <code>{inv['sync']}</code>")
        self.lay.addWidget(_label("myGeeKy found:<ul>" + "".join(f"<li>{f}</li>" for f in found) + "</ul>"))
        self.lay.addStretch(1)


class ChoosePage(Page):
    def __init__(self, inv: dict[str, Any]) -> None:
        super().__init__("Choose what to remove",
                         "Leave a box unticked to keep it. Kept data and tokens mean a reinstall picks up where you "
                         "left off.")
        self.inv = inv
        self.boxes: dict[str, QCheckBox] = {}
        holder = QWidget()
        body = QVBoxLayout(holder)
        body.setContentsMargins(0, 0, 8, 0)
        body.setSpacing(4)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(holder)
        self.lay.addWidget(scroll, 1)

        def option(key: str, text: str, explain: str, enabled: bool = True, checked: bool = False) -> None:
            box = QCheckBox(text)
            box.setChecked(checked)
            box.setEnabled(enabled)
            self.boxes[key] = box
            body.addWidget(box)
            note = _label(explain, "muted")
            note.setContentsMargins(30, 0, 0, 10)
            body.addWidget(note)

        option("program", "The myGeeKy program", "The package, the Start-menu and desktop shortcuts (or the apps-menu "
               "entry), and the weekly background task. Always removed.", enabled=False, checked=True)
        if inv["data"]:
            option("data", f"My data on this computer ({inv['data_size']})",
                   "Your settings, CV text, scholarly profile, history, your model and caches, in "
                   f"{inv['data_path']}. Without it, a reinstall starts from scratch.")
        if inv["tokens"]:
            option("tokens", f"My saved tokens and Signals key ({inv['tokens']})",
                   "Removed from your system keyring. The tokens still exist on GitHub until you revoke them there "
                   "(Settings → Developer settings → Personal access tokens, or Applications for 'Sign in with GitHub').")
        if inv["beacon_token"]:
            option("beacon", "Withdraw my Signals beacon",
                   "Publishes an empty beacon: other myGeeKy users stop seeing you, can't send you signals, and the "
                   "signals you sent disappear from their inbox. Needs your Signals token, so it runs before the "
                   "tokens are removed.")
        if inv["beacon"] or inv["beacon_token"]:
            option("beacon_repo", f"Open GitHub to delete my {inv['user']}/mygeeky-beacon repository",
                   "myGeeKy can't delete repositories (it never asks for that permission), so the repo's settings "
                   "page opens at the end, where 'Delete this repository' removes it and its history for good.")
        if inv["sync"]:
            option("sync_repo", f"Open GitHub to delete my private sync repository ({inv['sync']})",
                   "Your other computers sync through it. Its settings page opens at the end, so you can delete it "
                   "yourself.")
        body.addStretch(1)

    def chosen(self) -> dict[str, bool]:
        return {k: b.isChecked() for k, b in self.boxes.items()}


class SummaryPage(Page):
    def __init__(self) -> None:
        super().__init__("Please check before you uninstall", "")
        self.text = _label("")
        self.lay.addWidget(self.text)
        self.understand = QCheckBox("I understand that what I chose to erase can't be undone.")
        self.understand.toggled.connect(self.completeChanged)
        self.lay.addWidget(self.understand)
        self.lay.addStretch(1)
        self.setCommitPage(True)
        self.setButtonText(QWizard.CommitButton, "Uninstall")

    def initializePage(self) -> None:  # noqa: N802
        inv, c = self.w.inv, self.w.choose.chosen()
        will = ["Remove the myGeeKy program, its shortcuts and its weekly task."]
        keep = []
        if c.get("beacon"):
            will.append(f"<b>Withdraw your Signals beacon</b> ({inv['user']}/mygeeky-beacon): others stop seeing you.")
        if c.get("tokens"):
            will.append("<b>Delete your saved tokens and Signals key</b> from your system keyring.")
        elif inv["tokens"]:
            keep.append("your saved tokens and Signals key")
        if c.get("data"):
            will.append(f"<b>Erase your myGeeKy data</b> ({inv['data_size']}): settings, history, CV text, your model.")
        elif inv["data"]:
            keep.append(f"your data ({inv['data_path']})")
        opens = []
        if c.get("beacon_repo"):
            opens.append(f"{inv['user']}/mygeeky-beacon")
        if c.get("sync_repo"):
            opens.append(inv["sync"])
        if opens:
            will.append("Then open GitHub so you can delete " + " and ".join(f"<code>{o}</code>" for o in opens) + ".")
        html = "myGeeKy will:<ul>" + "".join(f"<li>{x}</li>" for x in will) + "</ul>"
        if keep:
            html += "It will keep " + ", ".join(keep) + ", so a reinstall picks up where you left off."
        self.text.setText(html)
        self.destructive = bool(c.get("data") or c.get("tokens") or c.get("beacon"))
        self.understand.setVisible(self.destructive)
        self.understand.setChecked(False)
        self.completeChanged.emit()

    def isComplete(self) -> bool:  # noqa: N802
        return not getattr(self, "destructive", False) or self.understand.isChecked()


class RunPage(Page):
    def __init__(self) -> None:
        super().__init__("Uninstalling myGeeKy", "")
        self.log = _label("Starting…")
        self.lay.addWidget(self.log)
        self.lay.addStretch(1)
        self.done = False

    def initializePage(self) -> None:  # noqa: N802
        self.lines: list[str] = []
        self.w.button(QWizard.BackButton).setEnabled(False)
        choice, inv, python = self.w.choose.chosen(), self.w.inv, self.w.python
        self._worker = Worker(lambda wk: run_steps(choice, inv, python, lambda line: wk.line.emit(line)))
        self._worker.line.connect(self._add)
        self._worker.done.connect(self._finished)
        self._worker.start()

    def _add(self, line: str) -> None:
        self.lines.append(line)
        self.log.setText("<br>".join(self.lines))

    def _finished(self, result: Any) -> None:
        if isinstance(result, dict) and result.get("error"):
            self._add(f"<span style='color:#f87171'>{result['error']}</span>")
        self._add("<br><b>Done.</b> Thank you for trying myGeeKy.")
        for url in (result or {}).get("open", []) if isinstance(result, dict) else []:
            QDesktopServices.openUrl(QUrl(url))
        self.done = True
        self.completeChanged.emit()

    def isComplete(self) -> bool:  # noqa: N802
        return self.done


def run_steps(choice: dict[str, bool], inv: dict[str, Any], python: str, say) -> dict[str, Any]:
    """Withdraw the beacon, remove tokens and data, then the program; say() each step."""
    from .. import uninstall as un
    from .setup_wizard import stop_running_panels
    opens = []
    stop_running_panels()
    say("✓ Closed the myGeeKy panel.")
    if choice.get("beacon"):
        try:
            from .. import beacon
            beacon.withdraw(load_config())
            say("✓ Withdrew your Signals beacon: others no longer see you.")
        except Exception as exc:
            say(f"✗ Couldn't withdraw your beacon ({exc}). You can delete the repo on GitHub instead.")
    if choice.get("tokens"):
        n = un.erase_tokens(inv["user"])
        say(f"✓ Removed {n} saved token{'s' if n != 1 else ''} and keys from your keyring.")
    if choice.get("data"):
        say("✓ Erased your myGeeKy data." if un.erase_data(DATA_DIR)
            else f"✗ Some of your data couldn't be removed: delete {DATA_DIR} by hand.")
    for note in uninstall(python, erase=False):
        if "were kept" not in note:
            say(("✓ " if "Removed" in note else "") + note)
    say("✓ Removed the shortcuts and the weekly task.")
    if choice.get("beacon_repo") and inv["user"]:
        opens.append(f"https://github.com/{inv['user']}/mygeeky-beacon/settings")
    if choice.get("sync_repo") and inv["sync"]:
        opens.append(f"https://github.com/{inv['sync']}/settings")
    if opens:
        say("Opening GitHub: scroll to the bottom of the page for 'Delete this repository'.")
    return {"open": opens}


class UninstallWizard(QWizard):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Uninstall myGeeKy")
        self.setWizardStyle(QWizard.ModernStyle)
        self.setStyleSheet(STYLE)
        self.setMinimumSize(700, 640)
        self.setOption(QWizard.NoCancelButtonOnLastPage, True)
        self.python = sys.executable if not FROZEN else (find_python() or "")
        self.inv = inventory()
        self.choose = ChoosePage(self.inv)
        for page in (IntroPage(self.inv), self.choose, SummaryPage(), RunPage()):
            self.addPage(page)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    wiz = UninstallWizard()
    wiz.show()
    wiz.raise_()
    wiz.activateWindow()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
