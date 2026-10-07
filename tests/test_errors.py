import subprocess
import sys

import pytest

from mygeeky import errors


def _launch_missing(program="definitely-not-a-real-program-xyz"):
    try:
        subprocess.run([program, "--version"], capture_output=True)
    except FileNotFoundError as exc:   # the bare "[WinError 2] The system cannot find the file specified"
        return exc
    pytest.skip("the program unexpectedly exists")


def test_a_bare_winerror_2_from_a_launch_names_the_program():
    msg = errors.describe(_launch_missing())
    assert "definitely-not-a-real-program-xyz" in msg and "WinError" not in msg


def test_known_programs_get_a_specific_hint():
    exc = _launch_missing("git-missing-for-test")
    assert "git-missing-for-test" in errors.describe(exc)
    assert "git-scm.com" in errors.PROGRAM_HINTS["git"]


def test_missing_files_and_permissions_are_named():
    assert "C:/x/cv.pdf" in errors.describe(FileNotFoundError(2, "No such file", "C:/x/cv.pdf"))
    assert "locked.json" in errors.describe(PermissionError(13, "Access denied", "locked.json"))


def test_crash_report_has_the_details(tmp_path):
    try:
        raise ValueError("boom")
    except ValueError as exc:
        path = errors.save_crash_report(exc, tmp_path, "test")
    text = path.read_text(encoding="utf-8")
    assert "What went wrong: ValueError: boom" in text and "Traceback" in text


def test_cli_turns_a_crash_into_a_message_and_a_report(monkeypatch, capsys, tmp_path):
    import mygeeky.cli as cli
    import mygeeky.config as config_module

    def broken(*a, **k):
        raise _launch_missing()
    monkeypatch.setattr(cli, "main", broken)
    monkeypatch.setattr(config_module, "LOG_DIR", tmp_path)
    with pytest.raises(SystemExit) as stop:
        cli.entry()
    assert stop.value.code == 1
    err = capsys.readouterr().err
    assert "myGeeKy hit a problem: Couldn't start definitely-not-a-real-program-xyz" in err
    assert "Full details were saved to" in err and list(tmp_path.glob("error-*.txt"))


# ---- the installer (the friend's actual case: Store Python only, and no winget)
sw = pytest.importorskip("mygeeky.gui.setup_wizard")


def test_installer_run_names_a_missing_program(monkeypatch, tmp_path):
    monkeypatch.setattr(sw, "SETUP_LOG", tmp_path / "setup.log")
    with pytest.raises(sw.SetupError, match="winget"):
        sw._run(["winget-missing-for-test", "install"])
    assert "winget-missing-for-test" in (tmp_path / "setup.log").read_text(encoding="utf-8")


def test_without_winget_python_comes_from_python_org(monkeypatch, tmp_path):
    monkeypatch.setattr(sw, "SETUP_LOG", tmp_path / "setup.log")
    calls = []

    def fake_run(cmd, stdin=None, timeout=600):
        calls.append(cmd[0])
        if cmd[0] == "winget":
            raise sw.SetupError("Couldn't start winget (Windows' app installer): it isn't installed on this PC.")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(sw, "_run", fake_run)
    found = iter([r"C:\Users\x\AppData\Local\Programs\Python\Python312\python.exe"])
    monkeypatch.setattr(sw, "find_python", lambda: next(found, None))
    downloads = []
    monkeypatch.setattr("urllib.request.urlretrieve", lambda url, target: downloads.append(url))
    said = []
    assert sw.install_python(said.append).endswith("python.exe")
    assert downloads == [sw.PYTHON_ORG_INSTALLER]
    assert calls[0] == "winget" and calls[1].endswith("python-3.12.10-amd64.exe")
    assert any("isn't on this PC" in s for s in said)


def test_api_explains_a_python_without_mygeeky(monkeypatch, tmp_path):
    monkeypatch.setattr(sw, "SETUP_LOG", tmp_path / "setup.log")
    monkeypatch.setattr(sw, "_run", lambda cmd, stdin=None, timeout=600: subprocess.CompletedProcess(
        cmd, 1, "", "Traceback...\nModuleNotFoundError: No module named 'mygeeky'"))
    result = sw.api(sys.executable, "status")
    assert not result["ok"] and "isn't installed" in result["error"]
