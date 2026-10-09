"""Regression tests for the failures found by stability/probes.py (see stability/REPORT.md)."""

import json
import time

import pytest
import requests

from mygeeky import config, files, github_client, scheduler, storage, sync
from mygeeky.errors import describe


# ---------------------------------------------------------------- data files (D1-D4)
def test_a_save_replaces_the_file_in_one_step(tmp_path):
    path = tmp_path / "state.json"
    files.write_json(path, {"a": 1})
    files.write_json(path, {"a": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 2}
    assert not list(tmp_path.glob("*.tmp"))                      # nothing left behind


def test_a_damaged_file_is_kept_aside_and_the_default_used(tmp_path):
    path = tmp_path / "excluded.json"
    path.write_text('["a", "b', encoding="utf-8")
    assert files.read_json(path, []) == []
    assert not path.exists() and len(list(tmp_path.glob("excluded.json.broken-*"))) == 1


def test_a_bom_from_a_text_editor_is_fine(tmp_path):
    path = tmp_path / "x.json"
    path.write_bytes(b"\xef\xbb\xbf" + b'{"ok": true}')
    assert files.read_json(path) == {"ok": True}


def test_a_half_written_history_line_is_skipped_and_the_next_one_starts_fresh(tmp_path):
    path = tmp_path / "h.jsonl"
    files.append_jsonl(path, {"n": 1})
    with open(path, "a", encoding="utf-8") as fh:
        fh.write('{"n": 2, "cut sho')                            # the process died here
    files.append_jsonl(path, {"n": 3})
    assert [r["n"] for r in files.read_jsonl(path)] == [1, 3]
    assert [r["n"] for r in storage.read_jsonl(path)] == [1, 3]


def test_damaged_settings_come_back_from_the_previous_save():
    config.save_config(config.MyGeekyConfig(github_username="octo"))
    config.save_config(config.MyGeekyConfig(github_username="octo", gui_theme="aurora"))
    config.CONFIG_FILE.write_text('{"github_username": "oc', encoding="utf-8")
    cfg = config.load_config()
    assert cfg.github_username == "octo" and config.RECOVERED_FROM == "config.previous.json"
    assert config._readable(config.CONFIG_FILE)["github_username"] == "octo"     # written back
    assert list(config.CONFIG_FILE.parent.glob("config.json.broken-*"))         # and the damaged one kept
    config.RECOVERED_FROM = ""


def test_a_damaged_synced_copy_never_replaces_good_settings():
    config.save_config(config.MyGeekyConfig(github_username="octo"))
    config.SYNCED_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.SYNCED_CONFIG_FILE.write_text("{broken", encoding="utf-8")
    assert sync.import_config() is False
    assert config.load_config().github_username == "octo"


def test_backups_and_broken_files_are_never_synced():
    for name in ("config.previous.json", "config.backup-*.json", "*.broken-*", "*.tmp"):
        assert name in sync.GITIGNORE.splitlines()


# ---------------------------------------------------------------- GitHub limits and odd networks (N1, N2, N7, N9)
class _R:
    def __init__(self, code=200, body=None, headers=None, text=None):
        self.status_code, self._body, self.headers = code, body or {}, headers or {}
        self.text = text if text is not None else json.dumps(self._body)

    def json(self):
        return self._body


def test_an_hour_long_limit_is_reported_not_slept(monkeypatch):
    slept = []
    monkeypatch.setattr(github_client.time, "sleep", slept.append)
    c = github_client.GitHubClient(token=None, rate_limit_sleep=0)
    reset = int(time.time()) + 3600
    c.session.get = lambda *a, **k: _R(200, {"login": "x"}, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset)})
    assert c.get_user("x") == {"login": "x"}                     # this answer is still good
    with pytest.raises(github_client.RateLimited) as err:
        c.get_user("y")
    assert not slept and time.strftime("%H:%M", time.localtime(reset)) in describe(err.value)
    assert isinstance(err.value, requests.RequestException)      # every network-error handler copes


def test_a_slow_down_reply_waits_briefly_then_retries(monkeypatch):
    slept = []
    monkeypatch.setattr(github_client.time, "sleep", slept.append)
    replies = [_R(429, {"message": "secondary rate limit"}, {"Retry-After": "5"}), _R(200, {"login": "x"})]
    c = github_client.GitHubClient(token=None, rate_limit_sleep=0)
    c.session.get = lambda *a, **k: replies.pop(0)
    assert c.get_user("x") == {"login": "x"} and slept == [5.0]


def test_a_long_slow_down_is_reported(monkeypatch):
    monkeypatch.setattr(github_client.time, "sleep", lambda s: None)
    c = github_client.GitHubClient(token=None, rate_limit_sleep=0)
    c.session.get = lambda *a, **k: _R(403, {"message": "You have exceeded a secondary rate limit"}, {"Retry-After": "600"})
    with pytest.raises(github_client.RateLimited, match="slow down"):
        c.get_user("x")


def test_a_wifi_sign_in_page_is_named_as_such():
    c = github_client.GitHubClient(token=None, rate_limit_sleep=0)
    c.session.get = lambda *a, **k: _R(200, None, {"Content-Type": "text/html"}, text="<!DOCTYPE html><html>Log in</html>")
    with pytest.raises(github_client.NotGitHub) as err:
        c.get_user("x")
    assert "Wi-Fi sign-in" in describe(err.value)


def test_a_certificate_problem_is_not_called_no_internet():
    msg = describe(requests.exceptions.SSLError("CERTIFICATE_VERIFY_FAILED"))
    assert "secure connection" in msg and "Couldn't reach the internet" not in msg


# ---------------------------------------------------------------- git sync (G1, G1b)
def test_background_git_never_prompts_and_has_a_time_limit(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(cmd=cmd, **kw)
        class P:
            returncode, stdout, stderr = 0, "", ""
        return P()
    monkeypatch.setattr(sync.winproc, "run", fake_run)
    sync._git("pull", check=False)
    assert seen["env"]["GIT_TERMINAL_PROMPT"] == "0" and seen["env"]["GCM_INTERACTIVE"] == "never"
    assert seen["timeout"] <= 300 and "http.lowSpeedTime=60" in seen["cmd"]


def test_only_the_first_setup_may_ask_git_to_sign_in(monkeypatch):
    envs = []

    def fake_init(repo):
        sync._git("fetch", check=False)
        return "ok"
    monkeypatch.setattr(sync, "_init", fake_init)
    monkeypatch.setattr(sync.winproc, "run", lambda cmd, **kw: envs.append(kw["env"]) or type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    sync.init("me/mygeeky-data")
    assert "GIT_TERMINAL_PROMPT" not in envs[0] or envs[0]["GIT_TERMINAL_PROMPT"] != "0"
    assert sync._interactive is False                            # and it's switched back off


def test_a_git_that_hangs_becomes_a_message(monkeypatch):
    import subprocess

    def hang(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])
    monkeypatch.setattr(sync.winproc, "run", hang)
    with pytest.raises(sync.SyncError, match="didn't finish"):
        sync._git("push")


# ---------------------------------------------------------------- weekly run (S1)
def test_the_cron_line_survives_spaces_and_replaces_an_old_line(monkeypatch):
    monkeypatch.setattr(scheduler, "_python_and_module", lambda: ("/home/a user/my apps/bin/python", "mygeeky.cli"))
    line = scheduler.cron_line()
    assert "'/home/a user/my apps/bin/python' -m mygeeky pipeline" in line and line.count("mkdir -p") == 1
    old = "0 9 * * 1 /usr/bin/python3 -m mygeeky pipeline >> ~/.local/share/mygeeky/logs/weekly.log 2>&1"
    written = {}
    monkeypatch.setattr(scheduler.platform, "system", lambda: "Linux")

    def fake(cmd, shell=True, capture_output=True, text=True, input=None):
        if cmd == "crontab -l":
            return type("R", (), {"returncode": 0, "stdout": f"MAILTO=me\n{old}\n"})()
        written["tab"] = input
        return type("R", (), {"returncode": 0, "stderr": ""})()
    monkeypatch.setattr(scheduler.subprocess, "run", fake)
    scheduler.install(confirmed=True)
    assert old not in written["tab"] and line in written["tab"] and "MAILTO=me" in written["tab"]
    scheduler.remove()
    assert scheduler.CRON_MARK not in written["tab"] and "MAILTO=me" in written["tab"]
