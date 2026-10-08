import subprocess
import sys

import pytest

from mygeeky import scheduler, winproc


def test_hidden_adds_no_window_and_a_hidden_start_on_windows(monkeypatch):
    if sys.platform != "win32":
        assert winproc.hidden({"cwd": "x"}) == {"cwd": "x"}
        return
    kw = winproc.hidden({"capture_output": True})
    assert kw["creationflags"] & winproc.CREATE_NO_WINDOW and kw["startupinfo"].wShowWindow == 0
    detached = winproc.hidden({"creationflags": 0x00000008})            # starting a GUI program detached
    assert detached["creationflags"] == 0x00000008


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_a_console_program_runs_and_its_output_is_captured():
    r = winproc.run([sys.executable, "-c", "print('hi')"], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "hi"


def test_every_background_command_goes_through_winproc():
    from pathlib import Path
    src = Path(scheduler.__file__).parent
    allowed = {"winproc.py", "desktop.py"}                 # desktop.py: Linux menus, and the detached pythonw start
    offenders = []
    for f in src.rglob("*.py"):
        if f.name in allowed:
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#")[0]
            if ("subprocess.run(" in code or "subprocess.Popen(" in code) and "crontab" not in code \
                    and "pythonw" not in code and "f\"subprocess" not in code and "(cmd).returncode" not in code:
                offenders.append(f"{f.name}:{i}")
    assert offenders == []


def test_the_weekly_task_uses_pythonw(monkeypatch, tmp_path):
    exe = tmp_path / "python.exe"
    exe.write_text("")
    (tmp_path / "pythonw.exe").write_text("")
    monkeypatch.setattr(sys, "executable", str(exe))
    assert "pythonw.exe" in scheduler.windows_command()


def test_an_old_weekly_task_is_switched_to_pythonw(monkeypatch):
    monkeypatch.setattr(scheduler.platform, "system", lambda: "Windows")
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        out = 'Task To Run: "C:\Py\python.exe" -m mygeeky pipeline' if "/Query" in cmd else ""
        return subprocess.CompletedProcess(cmd, 0, out, "")
    monkeypatch.setattr(scheduler.winproc, "run", run)
    assert scheduler.make_windowless() and "/Create" in calls[-1]
    calls.clear()
    monkeypatch.setattr(scheduler.winproc, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 0, 'Task To Run: "C:\Py\pythonw.exe" -m mygeeky pipeline', ""))
    assert not scheduler.make_windowless()                       # already windowless: left alone
