from datetime import datetime, timedelta, timezone

import pytest

from mygeeky import tokens
from mygeeky.config import MyGeekyConfig

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def test_parse_github_expiry_header():
    assert tokens.parse_expiry("2026-10-18 04:23:30 UTC") == datetime(2026, 10, 18, 4, 23, 30, tzinfo=timezone.utc)
    assert tokens.parse_expiry("2026-10-18 04:23:30 -0700").utcoffset() == timedelta(hours=-7)
    assert tokens.parse_expiry(None) is None and tokens.parse_expiry("soon") is None


@pytest.mark.parametrize("delta, warn, words", [
    (timedelta(days=30), False, "30 days left"),
    (timedelta(days=5, hours=2), True, "expires in 5 days"),
    (timedelta(hours=3), True, "expires today"),
    (timedelta(days=-2), True, "expired on"),
])
def test_describe_warns_from_a_week_before(delta, warn, words):
    out = tokens.describe({"name": "read", "state": "ok", "expires_at": (NOW + delta).isoformat()}, now=NOW)
    assert out["warn"] is warn and words in out["message"]
    if warn:
        assert "mygeeky auth login" in out["message"]


def test_describe_never_expiring_and_revoked():
    assert tokens.describe({"name": "beacon", "state": "ok", "expires_at": None})["message"] == \
        "Token 2 (Signals) never expires."
    revoked = tokens.describe({"name": "beacon", "state": "expired", "expires_at": None})
    assert revoked["warn"] and "mygeeky beacon init" in revoked["message"]


def test_status_checks_at_most_daily_and_rechecks_when_tokens_change(monkeypatch):
    stored = {"read": "t1"}
    monkeypatch.setattr(tokens, "_stored_tokens", lambda user: dict(stored))
    probes = []
    monkeypatch.setattr(tokens, "probe", lambda tok, timeout=10.0: probes.append(tok) or
                        {"state": "ok", "expires_at": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()})
    cfg = MyGeekyConfig(github_username="me")
    first = tokens.status(cfg)
    assert [t["name"] for t in first] == ["read"] and first[0]["warn"] and probes == ["t1"]
    tokens.status(cfg)
    assert probes == ["t1"]                   # cached: no second request
    stored["beacon"] = "t2"                    # a token was added: check again
    assert [t["name"] for t in tokens.status(cfg)] == ["read", "beacon"]
    assert probes == ["t1", "t1", "t2"]
    assert "t1" not in tokens.TOKEN_CHECK_FILE.read_text(encoding="utf-8")   # only dates are cached


def test_replace_token_refuses_someone_elses(monkeypatch):
    from mygeeky.gui import app as logic

    class Client:
        def __init__(self, *a, **k):
            pass

        def get_authenticated_user(self):
            return {"login": "stranger"}
    monkeypatch.setattr(logic, "GitHubClient", Client)
    stored = []
    import keyring
    monkeypatch.setattr(keyring, "set_password", lambda *a: stored.append(a))
    result = logic.replace_token(MyGeekyConfig(github_username="me"), "read", "github_pat_x")
    assert not result["ok"] and "stranger" in result["message"] and stored == []


def test_auth_status_shows_expiry(monkeypatch):
    from click.testing import CliRunner

    import mygeeky.cli as cli
    from mygeeky.config import save_config
    save_config(MyGeekyConfig(github_username="me"))
    monkeypatch.setattr(tokens, "status", lambda cfg, force=False: [tokens.describe(
        {"name": "read", "state": "ok", "expires_at": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()})])
    out = CliRunner().invoke(cli.main, ["auth", "status"]).output
    assert "Token 1 (read-only) expires in" in out and "Regenerate token" in out
