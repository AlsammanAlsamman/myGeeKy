import pytest

from mygeeky import github_login as gl
from mygeeky import setup_api, token_check
from mygeeky.config import MyGeekyConfig, load_config, save_config


class R:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status

    def json(self):
        return self._data


def test_start_asks_for_no_scopes(monkeypatch):
    sent = {}

    def post(url, data=None, headers=None, timeout=None):
        sent.update(url=url, data=data)
        return R({"device_code": "dc", "user_code": "ABCD-1234", "verification_uri": "https://github.com/login/device",
                  "interval": 5, "expires_in": 900})
    monkeypatch.setattr(gl.requests, "post", post)
    flow = gl.start()
    assert flow["user_code"] == "ABCD-1234" and sent["data"] == {"client_id": gl.CLIENT_ID, "scope": ""}


def test_poll_waits_slows_down_and_returns_the_token(monkeypatch):
    answers = iter([{"error": "authorization_pending"}, {"error": "slow_down", "interval": 10},
                    {"error": "authorization_pending"}, {"access_token": "gho_abc"}])
    monkeypatch.setattr(gl.requests, "post", lambda *a, **k: R(next(answers)))
    waits = []
    assert gl.poll("dc", 5, 900, sleep=waits.append) == "gho_abc"
    assert waits == [5, 5, 10, 10]                 # GitHub's "slow down" is respected


@pytest.mark.parametrize("error, message", [("access_denied", "cancelled"), ("expired_token", "expired"),
                                            ("incorrect_client_credentials", "failed")])
def test_poll_explains_why_it_stopped(monkeypatch, error, message):
    monkeypatch.setattr(gl.requests, "post", lambda *a, **k: R({"error": error}))
    with pytest.raises(gl.LoginError, match=message):
        gl.poll("dc", 1, 900, sleep=lambda s: None)


def test_setup_stores_the_sign_in_for_the_right_account_only(monkeypatch):
    save_config(MyGeekyConfig(github_username="me"))
    monkeypatch.setattr(gl, "poll", lambda *a, **k: "gho_abc")
    stored = []
    monkeypatch.setattr(gl, "store", lambda token, login: stored.append((token, login)))
    monkeypatch.setattr(gl, "who", lambda token: "someone-else")
    r = setup_api.github_login_finish({"device_code": "dc"})
    assert not r["ok"] and "someone-else" in r["error"] and not stored
    monkeypatch.setattr(gl, "who", lambda token: "Me")
    r = setup_api.github_login_finish({"device_code": "dc"})
    assert r["ok"] and r["login"] == "Me" and stored == [("gho_abc", "Me")]
    assert "gho_abc" not in str(r)                 # the token never comes back to the installer


def test_sign_in_fills_in_the_username_when_none_is_set(monkeypatch):
    save_config(MyGeekyConfig())
    monkeypatch.setattr(gl, "poll", lambda *a, **k: "gho_abc")
    monkeypatch.setattr(gl, "who", lambda token: "newbie")
    monkeypatch.setattr(gl, "store", lambda token, login: None)
    assert setup_api.github_login_finish({"device_code": "dc"})["ok"]
    assert load_config().github_username == "newbie"


def test_a_no_scope_sign_in_token_is_a_clean_token_1():
    caps = {"valid": True, "login": "me", "kind": "OAuth", "scopes": [], "can_follow": False,
            "beacon_write": False, "other_repo": "me/x", "other_write": False}
    v = token_check.judge("read", caps, "me")
    assert v["ok"] and v["warnings"] == []
    broad = dict(caps, scopes=["repo"], other_write=True)                # the GitHub CLI's token
    assert not token_check.judge("read", broad, "me")["ok"]
