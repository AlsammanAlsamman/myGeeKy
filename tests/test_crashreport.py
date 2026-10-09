import os
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from mygeeky import crashreport


def _boom():
    raise ValueError("bad feed date")


def _exc():
    try:
        _boom()
    except ValueError as exc:
        return exc


@pytest.fixture
def hooks():
    """install() replaces the process-wide hooks: put them back afterwards."""
    saved = sys.excepthook, threading.excepthook
    yield
    sys.excepthook, threading.excepthook = saved
    import faulthandler
    faulthandler.disable()
    if crashreport._fatal_handle:
        crashreport._fatal_handle.close()
        crashreport._fatal_handle = None


def test_nothing_personal_leaves_the_computer(monkeypatch):
    monkeypatch.setattr(crashreport, "_safe_user", lambda: "jdoe")
    home = str(Path.home())
    text = (f'File "{home}\\AppData\\mygeeky\\x.py", line 3\n'
            "token ghp_" + "a" * 36 + " and github_pat_" + "B" * 40 + "\n"
            "mail jane.doe@uni.edu, user JDoe, login octo-dev\n")
    clean = crashreport.redact(text, login="octo-dev")
    for secret in (home, "ghp_", "github_pat_", "jane.doe@uni.edu", "JDoe", "octo-dev"):
        assert secret not in clean
    assert "~" in clean and "<token>" in clean and "<email>" in clean and "<you>" in clean


def test_the_issue_is_prefilled_titled_and_short_enough(tmp_path):
    path = crashreport.write(tmp_path, "panel", _exc())
    report = path.read_text(encoding="utf-8")
    assert "where: panel" in report and "myGeeKy" in report and "ValueError: bad feed date" in report
    url = crashreport.issue_url(report + "\n" + "x = 1\n" * 3000, note="I clicked News")
    q = parse_qs(urlparse(url).query)
    assert url.startswith("https://github.com/mygeeky/myGeeKy/issues/new?")
    assert q["title"] == ["💥 ValueError in _boom"] and q["labels"] == ["crash"]
    assert q["body"][0].startswith("I clicked News") and len(url) <= crashreport.MAX_URL


def test_errors_on_any_thread_become_one_report_each(tmp_path, hooks):
    got = []
    crashreport.install(tmp_path, on_report=got.append)
    exc = _exc()
    sys.excepthook(type(exc), exc, exc.__traceback__)
    sys.excepthook(type(exc), exc, exc.__traceback__)            # the same error again: not a second report
    t = threading.Thread(target=_boom, name="news-refresh")
    t.start(); t.join()                                           # noqa: E702
    where = sorted(p.read_text(encoding="utf-8").splitlines()[0] for p in got)
    assert len(got) == 2 and where == ["where: background task (news-refresh)", "where: panel"]


def test_reports_are_offered_once_and_old_ones_not_at_all(tmp_path):
    new = crashreport.write(tmp_path, "panel", _exc())
    old = tmp_path / "error-20200101-000000.txt"
    old.write_text("old", encoding="utf-8")
    os.utime(old, (0, 0))
    assert crashreport.pending(tmp_path) == [new]
    crashreport.mark_offered(tmp_path, [new.name])
    assert crashreport.pending(tmp_path) == []


def test_a_hard_crash_is_reported_on_the_next_start(tmp_path, hooks):
    # a real crash: the process dies outright, no Python exception to catch
    code = ("import sys, faulthandler; sys.path.insert(0, sys.argv[2]); from mygeeky import crashreport; "
            "from pathlib import Path; crashreport.install(Path(sys.argv[1])); faulthandler._sigsegv()")
    src = str(Path(crashreport.__file__).parents[1])
    r = subprocess.run([sys.executable, "-c", code, str(tmp_path), src], capture_output=True)
    assert r.returncode != 0 and crashreport.pending(tmp_path) == []
    crashreport.install(tmp_path)                                  # the next start
    [report] = crashreport.pending(tmp_path)
    text = report.read_text(encoding="utf-8")
    assert "hard crash" in text and ("Fatal Python error" in text or "Windows fatal exception" in text)
    crashreport.install(tmp_path)                                  # and only once
    assert len(list(tmp_path.glob("crash-*.txt"))) == 1


def test_the_crash_window_shows_the_cleaned_report_without_locking(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from mygeeky.gui.crash_dialog import CrashDialog
    monkeypatch.setattr(crashreport, "_safe_user", lambda: "jdoe")
    path = crashreport.write(tmp_path, "panel", _exc(), text="token ghp_" + "z" * 36 + " for jdoe\n")
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    dlg = CrashDialog(None, [path], tmp_path, login="me")
    shown = dlg.view.toPlainText()
    assert "ghp_" not in shown and "jdoe" not in shown and dlg.isModal() is False
    assert crashreport.pending(tmp_path) == []                     # "Not now" doesn't bring it back
    dlg._send()
    for t in threading.enumerate():
        if t is not threading.current_thread() and t.daemon:
            t.join(2)
    assert opened and "issues/new" in opened[0] and "ghp_" not in opened[0]
    dlg.close()


def test_two_errors_in_the_same_instant_are_two_reports(tmp_path, monkeypatch):
    class Frozen:                                   # Windows' clock often repeats a microsecond
        @staticmethod
        def now(tz=None):
            from datetime import datetime as real
            return real(2026, 10, 9, 12, 0, 0, 123456)
    monkeypatch.setattr(crashreport, "datetime", Frozen)
    a = crashreport.write(tmp_path, "panel", _exc())
    b = crashreport.write(tmp_path, "background task (x)", _exc())
    assert a != b and a.read_text(encoding="utf-8").startswith("where: panel")
