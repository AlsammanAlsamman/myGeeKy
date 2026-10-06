import sys

import mygeeky.__main__ as entry
from mygeeky.gui import bootstrap

STORE_SITE = (r"C:\Users\someone\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0"
              r"\LocalCache\local-packages\Python313\site-packages")
NORMAL_SITE = r"C:\Users\someone\AppData\Local\Programs\Python\Python313\Lib\site-packages"


def test_store_python_folder_is_too_deep_for_qt_unless_long_paths(monkeypatch):
    monkeypatch.setattr(bootstrap, "_long_paths_enabled", lambda: False)
    assert bootstrap.paths_fit(NORMAL_SITE)
    assert not bootstrap.paths_fit(STORE_SITE)
    monkeypatch.setattr(bootstrap, "_long_paths_enabled", lambda: True)
    assert bootstrap.paths_fit(STORE_SITE)


def test_install_goes_to_private_folder_when_paths_dont_fit(monkeypatch, tmp_path):
    monkeypatch.setenv("MYGEEKY_QT_DIR", str(tmp_path / "qt"))
    monkeypatch.setattr(bootstrap, "paths_fit", lambda install_dir=None: False)
    monkeypatch.setattr(bootstrap, "qt_available", lambda: True)
    calls = []

    class Done:
        returncode = 0
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or Done())
    assert bootstrap.install_qt(log=lambda m: None)
    cmd = calls[0]
    assert cmd[:4] == [sys.executable, "-m", "pip", "install"] and bootstrap.QT_REQUIREMENT in cmd
    assert cmd[cmd.index("--target") + 1] == str(tmp_path / "qt")


def test_install_uses_normal_location_when_paths_fit(monkeypatch):
    monkeypatch.setattr(bootstrap, "paths_fit", lambda install_dir=None: True)
    monkeypatch.setattr(bootstrap, "qt_available", lambda: True)
    calls = []

    class Done:
        returncode = 0
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or Done())
    bootstrap.install_qt(log=lambda m: None)
    assert "--target" not in calls[0]


def test_ensure_qt_exits_with_a_clear_message_when_install_fails(monkeypatch):
    monkeypatch.setattr(bootstrap, "qt_available", lambda: False)
    monkeypatch.setattr(bootstrap, "install_qt", lambda log=print: False)
    try:
        bootstrap.ensure_qt(interactive=False)
    except SystemExit as exc:
        assert "pip install" in str(exc)
    else:
        raise AssertionError("expected SystemExit")


def test_path_tip_never_interrupts_scripts_or_version(monkeypatch):
    asked = []
    monkeypatch.setattr("builtins.input", lambda prompt: asked.append(prompt) or "n")
    monkeypatch.setattr(entry.sys, "platform", "win32")

    class Tty:
        def isatty(self):
            return True
    monkeypatch.setattr(entry.sys, "stdin", Tty())
    monkeypatch.setattr(entry.sys, "stdout", Tty())
    monkeypatch.setattr(entry, "scripts_dir", lambda: entry.Path(r"C:\nowhere\Scripts"))
    monkeypatch.setattr(entry, "on_path", lambda d: False)
    for argv in (["m", "--version"], ["m", "run", "--json"], ["m"]):
        monkeypatch.setattr(entry.sys, "argv", argv)
        entry.offer_path_fix()
    assert asked == []
    monkeypatch.setattr(entry.sys, "argv", ["m", "init"])
    entry.offer_path_fix()
    entry.offer_path_fix()          # asked once, then remembered
    assert len(asked) == 1
