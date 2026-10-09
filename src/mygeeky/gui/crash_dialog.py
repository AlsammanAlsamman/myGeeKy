"""The "Something went wrong" window: shows a crash report (personal details
already removed) and opens it as a prefilled GitHub issue you submit yourself.
Nothing is sent from here."""

from __future__ import annotations

import threading
import webbrowser
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QVBoxLayout, QWidget)

from .. import crashreport


class CrashRelay(QObject):
    """Errors can happen on any thread; the window must open on the main one."""
    reported = Signal(str)


class CrashDialog(QDialog):
    def __init__(self, parent: QWidget | None, reports: list[Path], log_dir: Path, login: str = "",
                 theme: dict | None = None) -> None:
        super().__init__(parent)
        theme = theme or {"text": "#e8e8f0", "muted": "#9a9ab0", "btn_bg": "#2a2a3a", "btn_hover": "#34344a",
                          "accent": "#c084fc"}
        self.reports, self.log_dir, self.login = reports, log_dir, login
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)        # never hidden behind the panel
        self.setWindowModality(Qt.NonModal)                      # and never locks it
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle("myGeeKy: something went wrong")
        self.setMinimumSize(520, 420)
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        n = len(reports)
        intro = QLabel(
            ("myGeeKy hit an error" if n == 1 else f"myGeeKy hit {n} errors")
            + ". You can send the report to its maker as a GitHub issue so it gets fixed: your browser opens it "
            "ready to send, and you click <b>Submit</b> there. Below is <b>exactly</b> what it contains: tokens, "
            "email addresses, your name and your folders are already removed. It's public, so check it first.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.note = QPlainTextEdit()
        self.note.setPlaceholderText("What were you doing when it happened? (optional, helps a lot)")
        self.note.setFixedHeight(60)
        lay.addWidget(self.note)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setPlainText(self._text())
        lay.addWidget(self.view, 1)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        row = QHBoxLayout()
        folder = QPushButton("Open logs folder")
        folder.clicked.connect(self._open_folder)
        row.addWidget(folder)
        row.addStretch(1)
        later = QPushButton("Not now")
        later.clicked.connect(self.close)
        self.send = QPushButton("Report on GitHub ↗")
        self.send.clicked.connect(self._send)
        row.addWidget(later)
        row.addWidget(self.send)
        lay.addLayout(row)
        self.setStyleSheet(
            f"QDialog {{ background:#17171f; }} QLabel {{ color:{theme['text']}; font-size:11.5px; }}"
            f"QPlainTextEdit {{ background:#22222e; color:{theme['text']}; border:1px solid #34344a; "
            "border-radius:7px; padding:5px; font-family:Consolas, 'DejaVu Sans Mono', monospace; font-size:10.5px; }"
            f"QPushButton {{ background:{theme['btn_bg']}; color:{theme['text']}; border:none; border-radius:7px; "
            f"padding:6px 12px; }} QPushButton:hover {{ background:{theme['btn_hover']}; }}")
        # offered once: closing it ("Not now") doesn't bring the same report back on every start
        crashreport.mark_offered(log_dir, [crashreport.offer_key(p) for p in reports if p.exists()])

    def _raw(self) -> str:
        parts = []
        for p in self.reports[:3]:                    # a burst of the same error: the newest three
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            parts.append(text.strip())
        return "\n\n=====\n\n".join(parts)

    def _text(self) -> str:
        return crashreport.redact(self._raw(), self.login)

    def add(self, report: Path) -> None:
        """Another error while the window is open: add it instead of opening a second window."""
        if report not in self.reports:
            self.reports.insert(0, report)
            self.view.setPlainText(self._text())
            crashreport.mark_offered(self.log_dir, [crashreport.offer_key(report)])

    def _send(self) -> None:
        url = crashreport.issue_url(self._raw(), self.login, self.note.toPlainText())
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
        self.status.setText("✓ Your browser opened it on GitHub: click <b>Submit new issue</b> there to send it. "
                            "Thank you!")

    def _open_folder(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.log_dir)))
