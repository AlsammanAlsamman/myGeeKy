import base64
import json
from datetime import datetime, timedelta, timezone

import pytest

from mygeeky import beacon as bc
from mygeeky.config import MyGeekyConfig

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


def _cfg(**kw) -> MyGeekyConfig:
    return MyGeekyConfig(github_username="me", beacon_enabled=True, **kw)


def _raw(gestures, **kw):
    return {"mygeeky_beacon": 1, "status": kw.get("status", ""), "interests": kw.get("interests", []),
            "gestures": gestures}


# --------------------------------------------------------------------------- parsing untrusted beacons
def test_parse_beacon_keeps_only_valid_gestures():
    at = NOW.isoformat()
    raw = _raw([
        {"to": "me", "type": "wave", "at": at},
        {"to": "me", "type": "insult", "at": at},                        # not in the vocabulary
        {"to": "<script>", "type": "wave", "at": at},                    # not a GitHub login
        {"to": "me", "type": "kudos", "at": at},                         # kudos without a repo
        {"to": "me", "type": "kudos", "repo": "me/tool", "at": at},
        {"to": "me", "type": "wave", "at": (NOW - timedelta(days=200)).isoformat()},  # expired
        {"to": "me", "type": "wave", "at": (NOW + timedelta(days=30)).isoformat()},   # from the future
        {"to": "me", "type": "wave", "at": "yesterday"},
        "not a dict",
    ], status="hacked <b>", interests=["gwas", "<img src=x>", "a" * 80, "GWAS"])
    parsed = bc.parse_beacon(raw, "alice", ttl_days=90, now=NOW)
    assert parsed["owner"] == "alice"
    assert [(g["type"], g.get("repo")) for g in parsed["gestures"]] == [("wave", None), ("kudos", "me/tool")]
    assert parsed["status"] == ""            # unknown status dropped
    assert parsed["interests"] == ["gwas"]   # unsafe/oversized/duplicate tags dropped


@pytest.mark.parametrize("raw", [None, [], "x", {"mygeeky_beacon": 2, "gestures": []}, {"gestures": []}])
def test_parse_beacon_rejects_non_beacons(raw):
    assert bc.parse_beacon(raw, "alice", ttl_days=90, now=NOW) is None


def test_parse_beacon_owner_comes_from_repo_not_file():
    raw = _raw([]) | {"owner": "someone-else", "user": "someone-else"}
    assert bc.parse_beacon(raw, "alice", ttl_days=90, now=NOW)["owner"] == "alice"
    assert bc.parse_beacon(raw, "bad/owner", ttl_days=90, now=NOW) is None


# --------------------------------------------------------------------------- sending
def test_add_gesture_dedupes_and_validates():
    cfg = _cfg()
    b = bc.add_gesture(bc.empty_beacon(), "me", "alice", "wave", None, cfg, now=NOW)
    b = bc.add_gesture(b, "me", "alice", "wave", None, cfg, now=NOW + timedelta(hours=1))
    assert len(b["gestures"]) == 1 and b["gestures"][0]["at"].startswith("2026-10-06T13")
    b = bc.add_gesture(b, "me", "alice", "kudos", "alice/tool", cfg, now=NOW)
    assert len(b["gestures"]) == 2
    for args in [("me", "wave", None), ("alice", "hug", None), ("not valid!", "wave", None),
                 ("alice", "kudos", None)]:
        with pytest.raises(bc.BeaconError):
            bc.add_gesture(b, "me", *args, cfg, now=NOW)


def test_add_gesture_daily_limit_and_blocked():
    cfg = _cfg(beacon_daily_limit=2, beacon_blocked=["Troll"])
    b = bc.add_gesture(bc.empty_beacon(), "me", "a1", "wave", None, cfg, now=NOW)
    b = bc.add_gesture(b, "me", "a2", "wave", None, cfg, now=NOW)
    with pytest.raises(bc.BeaconError, match="Daily limit"):
        bc.add_gesture(b, "me", "a3", "wave", None, cfg, now=NOW)
    bc.add_gesture(b, "me", "a3", "wave", None, cfg, now=NOW + timedelta(days=1))  # tomorrow is fine
    with pytest.raises(bc.BeaconError, match="blocked"):
        bc.add_gesture(bc.empty_beacon(), "me", "troll", "wave", None, cfg, now=NOW)


def test_public_beacon_publishes_only_four_fields_and_prunes():
    cfg = _cfg(topics=["GWAS"], keywords=["fine mapping"], beacon_status="open-to-collab")
    mine = {"mygeeky_beacon": 1, "status": "", "interests": [], "gestures": [
        {"to": "a", "type": "wave", "at": datetime.now(timezone.utc).isoformat()},
        {"to": "b", "type": "wave", "at": "2020-01-01T00:00:00+00:00"},
    ], "secret": "x"}
    pub = bc.public_beacon(mine, cfg)
    assert set(pub) == {"mygeeky_beacon", "status", "interests", "gestures"}
    assert pub["status"] == "open-to-collab"
    assert pub["interests"] == ["gwas", "fine mapping"]
    assert [g["to"] for g in pub["gestures"]] == ["a"]
    assert bc.public_beacon(mine, _cfg(topics=["gwas"], beacon_share_interests=False))["interests"] == []


class _FakeResp:
    def __init__(self, status, data=None):
        self.status_code, self._data, self.text = status, data or {}, ""

    def json(self):
        return self._data


class _FakeSession:
    def __init__(self, existing=None, put_status=201):
        self.headers, self.calls, self.existing, self.put_status = {}, [], existing, put_status

    def get(self, url, timeout):
        self.calls.append(("GET", url, None))
        return _FakeResp(200, self.existing) if self.existing else _FakeResp(404)

    def put(self, url, json, timeout):
        self.calls.append(("PUT", url, json))
        return _FakeResp(self.put_status)


def test_writer_only_writes_its_own_beacon_repo():
    session = _FakeSession()
    w = bc.BeaconWriter("tok", "me", session=session)
    w.publish({"mygeeky_beacon": 1, "gestures": []})
    method, url, body = session.calls[-1]
    assert method == "PUT"
    assert url == "https://api.github.com/repos/me/mygeeky-beacon/contents/beacon.json"
    assert json.loads(base64.b64decode(body["content"]))["mygeeky_beacon"] == 1
    with pytest.raises(bc.BeaconError):
        w.write("../../other/repo", "x", "m")
    with pytest.raises(bc.BeaconError):
        bc.BeaconWriter("tok", "me/../evil")


def test_writer_updates_with_sha_and_skips_unchanged():
    text = json.dumps({"a": 1}, indent=2) + "\n"
    existing = {"sha": "abc", "content": base64.b64encode(text.encode()).decode()}
    session = _FakeSession(existing=existing)
    bc.BeaconWriter("tok", "me", session=session).publish({"a": 1})
    assert [c[0] for c in session.calls] == ["GET"]  # identical -> no commit
    session = _FakeSession(existing=existing)
    bc.BeaconWriter("tok", "me", session=session).publish({"a": 2})
    assert session.calls[-1][2]["sha"] == "abc"


def test_writer_explains_a_refused_token():
    with pytest.raises(bc.BeaconError, match="Contents: Read and write"):
        bc.BeaconWriter("tok", "me", session=_FakeSession(put_status=403)).publish({})


def test_send_publishes_before_saving_locally():
    cfg = _cfg()
    with pytest.raises(bc.BeaconError):
        bc.send(cfg, "alice", "wave", writer=bc.BeaconWriter("t", "me", session=_FakeSession(put_status=403)))
    assert bc.load_my_beacon()["gestures"] == []  # nothing recorded as sent
    bc.send(cfg, "alice", "wave", writer=bc.BeaconWriter("t", "me", session=_FakeSession()))
    assert [g["to"] for g in bc.load_my_beacon()["gestures"]] == ["alice"]
    assert bc.unsend(cfg, "alice", writer=bc.BeaconWriter("t", "me", session=_FakeSession())) == 1
    assert bc.load_my_beacon()["gestures"] == []


def test_send_requires_setup():
    with pytest.raises(bc.BeaconError, match="beacon init"):
        bc.send(MyGeekyConfig(github_username="me"), "alice", "wave")


# --------------------------------------------------------------------------- reading
class _FakeClient:
    def __init__(self, repos, files, by_name=()):
        self.repos, self.files, self.fetched, self.by_name = repos, files, [], list(by_name)

    def search_repositories(self, query, max_pages, per_page, sort):
        if "topic:mygeeky-beacon" in query:
            return self.repos
        assert "mygeeky-beacon in:name" in query
        return self.by_name

    def get_repo_file(self, owner_repo, path):
        self.fetched.append(owner_repo)
        raw = self.files.get(owner_repo.split("/")[0])
        if raw is None:
            return None
        text = json.dumps(raw).encode()
        return {"encoding": "base64", "size": len(text), "content": base64.b64encode(text).decode()}


def _repo(login, pushed="2026-10-05T00:00:00Z", name="mygeeky-beacon", typ="User"):
    return {"name": name, "pushed_at": pushed, "owner": {"login": login, "type": typ, "avatar_url": f"av/{login}"}}


def test_refresh_inbox_people_and_handshake():
    recent = datetime.now(timezone.utc).isoformat()
    client = _FakeClient(
        [_repo("alice"), _repo("bob"), _repo("me"), _repo("org", typ="Organization"),
         _repo("carol", name="other-repo"), _repo("troll")],
        {"alice": _raw([{"to": "me", "type": "wave", "at": recent},
                        {"to": "me", "type": "kudos", "repo": "me/tool", "at": recent},
                        {"to": "zed", "type": "wave", "at": recent}], interests=["gwas"]),
         "bob": _raw([], status="mentoring", interests=["rust"]),
         "troll": _raw([{"to": "me", "type": "wave", "at": recent}])})
    cfg = _cfg(topics=["gwas"], beacon_blocked=["troll"])
    cache = bc.refresh(client, cfg, force=True)
    assert set(cache["users"]) == {"alice", "bob", "troll"}   # self, orgs, other repos skipped

    mine = bc.add_gesture(bc.empty_beacon(), "me", "alice", "learn", None, cfg)
    rows = bc.inbox(cache, cfg, mine)
    assert {r["type"] for r in rows} == {"wave", "kudos"}
    assert all(r["from"] == "alice" and r["mutual"] for r in rows)
    assert "me/tool" in next(r for r in rows if r["type"] == "kudos")["text"]

    ppl = bc.people(cache, cfg, mine)
    assert [p["login"] for p in ppl] == ["alice", "bob"]       # signalled you first; troll blocked
    assert ppl[0]["shared"] == ["gwas"] and ppl[1]["status"] == bc.STATUSES["mentoring"]
    assert bc.suggestion_signals(cache, cfg) == {"alice": "signalled_you"}

    # unchanged repos are reused from the cache, not fetched again
    client.fetched.clear()
    bc.refresh(client, cfg, force=True)
    assert client.fetched == []


def test_refresh_respects_interval():
    cfg = _cfg(beacon_refresh_minutes=30)
    client = _FakeClient([_repo("alice")], {"alice": _raw([])})
    bc.refresh(client, cfg, force=True)
    client.fetched.clear()
    client.repos = [_repo("alice", pushed="2026-10-06T00:00:00Z")]
    bc.refresh(client, cfg)            # not due yet: no network
    assert client.fetched == []


def test_fetch_beacon_rejects_oversized():
    client = _FakeClient([], {})
    client.get_repo_file = lambda r, p: {"encoding": "base64", "size": bc.MAX_BEACON_BYTES + 1, "content": ""}
    assert bc.fetch_beacon(client, "alice") is None


def test_beacons_without_the_topic_are_found_by_name():
    recent = datetime.now(timezone.utc).isoformat()
    client = _FakeClient([_repo("alice")], {
        "alice": _raw([]),
        "newbie": _raw([{"to": "me", "type": "wave", "at": recent}]),
    }, by_name=[_repo("alice"), _repo("newbie"), _repo("copycat", name="not-mygeeky-beacon"),
                dict(_repo("secret"), private=True)])
    cfg = _cfg()
    cache = bc.refresh(client, cfg, force=True)
    assert set(cache["users"]) == {"alice", "newbie"}
    assert [r["from"] for r in bc.inbox(cache, cfg, bc.empty_beacon())] == ["newbie"]


def test_beacon_init_walks_through_repo_and_token_and_retries_a_bad_token(monkeypatch):
    from click.testing import CliRunner

    import mygeeky.cli as cli
    from mygeeky.config import save_config

    save_config(MyGeekyConfig(github_username="me"))
    repo_exists = iter([None, None, {"private": False, "topics": []}])

    class Client:
        def get_repo(self, name):
            return next(repo_exists, {"private": False, "topics": []})

    monkeypatch.setattr(cli, "_client_for", lambda cfg: Client())
    monkeypatch.setattr(cli.click, "launch", lambda url: None)
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(bc, "fetch_beacon", lambda client, owner: {"mygeeky_beacon": 1})
    published, stored = [], []
    monkeypatch.setattr(bc, "go_live", lambda cfg, writer=None: (
        published.append(writer.session.headers["Authorization"]),
        (_ for _ in ()).throw(bc.BeaconError("GitHub refused the write.")) if len(published) == 1 else None))
    import keyring
    monkeypatch.setattr(keyring, "set_password", lambda *a: stored.append(a))
    monkeypatch.setattr(cli.auth, "get_beacon_token", lambda user: None)

    # open page? y / repo created? (Enter) / open token page? y / bad token / good token
    result = CliRunner().invoke(cli.main, ["beacon", "init"], input="y\n\ny\nbad\ngood\n")
    assert result.exit_code == 0, result.output
    assert "Step 1 of 3" in result.output and "Step 3 of 3" in result.output
    assert "Only select repositories" in result.output and "Read and write" in result.output
    assert "GitHub refused the write" in result.output
    assert published == ["Bearer bad", "Bearer good"]
    assert stored == [(cli.auth.BEACON_SERVICE_NAME, "me", "good")]   # only the token that worked is kept
    assert "Your beacon is live" in result.output
