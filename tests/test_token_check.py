import pytest

from mygeeky import setup_api, token_check as tc
from mygeeky.config import MyGeekyConfig, save_config

READ_ONLY = {"valid": True, "login": "me", "kind": "fine-grained", "scopes": None, "can_follow": False,
             "beacon_write": False, "other_repo": "me/tool", "other_write": False}
BEACON = {**READ_ONLY, "beacon_write": True}
POWERFUL = {**READ_ONLY, "kind": "classic", "scopes": ["repo", "user"], "can_follow": True,
            "beacon_write": True, "other_write": True}


def test_token1_must_be_read_only():
    assert tc.judge("read", READ_ONLY, "me")["ok"]
    v = tc.judge("read", BEACON, "me")
    assert not v["ok"] and "write to me/mygeeky-beacon" in v["errors"][0] and "Signals page" in v["errors"][0]
    v = tc.judge("read", POWERFUL, "me")
    assert not v["ok"] and len(v["errors"]) == 2 and "follow" in v["errors"][1]


def test_token2_must_write_the_beacon_and_warns_when_broader():
    assert tc.judge("beacon", BEACON, "me")["ok"]
    v = tc.judge("beacon", READ_ONLY, "me")
    assert not v["ok"] and "can't write to me/mygeeky-beacon" in v["errors"][0]
    v = tc.judge("beacon", POWERFUL, "me")
    assert v["ok"] and any("also write to me/tool" in w for w in v["warnings"])


def test_the_same_token_twice_is_caught_both_ways():
    assert "Signals token" in tc.judge("read", BEACON, "me", other_token="x", token="x")["errors"][0]
    assert "same token as token 1" in tc.judge("beacon", BEACON, "me", other_token="x", token="x")["errors"][0]


def test_wrong_owner_and_bad_token():
    assert "belongs to me" in tc.judge("read", READ_ONLY, "you")["errors"][0]
    assert "didn't accept" in tc.judge("read", {"valid": False}, "me")["errors"][0]


def test_kind_of():
    assert [tc.kind_of(t) for t in ("github_pat_x", "ghp_x", "gho_x", "x")] == \
        ["fine-grained", "classic", "GitHub CLI", "other"]


class Resp:
    def __init__(self, code):
        self.status_code = code


def test_follow_probe_never_touches_someone_you_follow(monkeypatch):
    calls = []
    following = {"octocat"}
    monkeypatch.setattr(tc.requests, "get", lambda url, **kw: (calls.append(("GET", url)),
                        Resp(204 if url.rsplit("/", 1)[1] in following else 404))[1])
    monkeypatch.setattr(tc.requests, "delete", lambda url, **kw: (calls.append(("DELETE", url)), Resp(204))[1])
    assert tc._can_follow("t", 5) is True
    assert ("DELETE", f"{tc.API}/user/following/octocat") not in calls
    assert ("DELETE", f"{tc.API}/user/following/defunkt") in calls
    # no Followers permission at all: GitHub refuses the read, and nothing is sent
    calls.clear()
    monkeypatch.setattr(tc.requests, "get", lambda url, **kw: Resp(403))
    assert tc._can_follow("t", 5) is False and not [c for c in calls if c[0] == "DELETE"]


@pytest.mark.parametrize("code, expected", [(201, True), (403, False), (404, False), (409, None)])
def test_write_probe(monkeypatch, code, expected):
    monkeypatch.setattr(tc.requests, "post", lambda url, **kw: Resp(code))
    assert tc._can_write("t", "me/r", 5) is expected


def test_setup_refuses_a_write_token_as_token_1(monkeypatch):
    save_config(MyGeekyConfig(github_username="me"))
    monkeypatch.setattr(tc, "capabilities", lambda token, user, **kw: dict(BEACON))
    stored = []
    import keyring
    monkeypatch.setattr(keyring, "set_password", lambda *a: stored.append(a))
    r = setup_api.store_token({"token": "github_pat_x"})
    assert not r["ok"] and "Token 1 must be read-only" in r["error"] and stored == []
    monkeypatch.setattr(tc, "capabilities", lambda token, user, **kw: dict(READ_ONLY))
    r = setup_api.store_token({"token": "github_pat_y"})
    assert r["ok"] and r["notes"][0].startswith("Token 1 ✓") and len(stored) == 1


def test_setup_refuses_token_1_as_token_2(monkeypatch):
    save_config(MyGeekyConfig(github_username="me"))
    from mygeeky import auth, beacon
    monkeypatch.setattr(auth, "get_token", lambda user: "github_pat_one")
    published = []
    monkeypatch.setattr(beacon, "ensure_repo", lambda *a, **kw: [])
    monkeypatch.setattr(beacon, "go_live", lambda *a, **kw: published.append(a))
    monkeypatch.setattr(tc, "capabilities", lambda token, user, **kw: dict(READ_ONLY))
    r = setup_api.beacon_init({"token": "github_pat_one"})
    assert not r["ok"] and "same token as token 1" in r["error"] and not published
