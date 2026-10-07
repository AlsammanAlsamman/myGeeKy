import base64
import json
from datetime import datetime, timedelta, timezone

import pytest

from mygeeky import beacon as bc
from mygeeky import signal_crypto as sc
from mygeeky.config import MyGeekyConfig

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def memory_keyring(monkeypatch):
    """Never touch the real OS keyring: keys live in a dict for each test."""
    import keyring
    store: dict = {}
    monkeypatch.setattr(keyring, "get_password", lambda svc, user: store.get((svc, user)))
    monkeypatch.setattr(keyring, "set_password", lambda svc, user, pw: store.__setitem__((svc, user), pw))
    return store


def _cfg(**kw) -> MyGeekyConfig:
    kw.setdefault("github_username", "me")
    return MyGeekyConfig(beacon_enabled=True, **kw)


def _raw_v1(gestures, **kw):
    return {"mygeeky_beacon": 1, "status": kw.get("status", ""), "interests": kw.get("interests", []),
            "gestures": gestures}


class Person:
    """Another myGeeKy user with their own key, able to build a v2 beacon."""

    def __init__(self, login: str, **kw):
        self.login = login
        self.priv, self.pub = sc.new_keypair()
        self.extra = kw
        self.sealed: list[dict] = []

    def send(self, to_pub: str, to: str, gesture: str, at: datetime = None, repo=None, sender=None):
        msg = {"v": 2, "from": sender or self.login, "to": to, "type": gesture,
               "at": (at or datetime.now(timezone.utc)).isoformat()}
        if repo:
            msg["repo"] = repo
        self.sealed.append({"at": (at or datetime.now(timezone.utc)).date().isoformat(),
                            "box": sc.seal(to_pub, json.dumps(msg).encode())})

    def raw(self):
        return {"mygeeky_beacon": 2, "keys": [self.pub], "status": self.extra.get("status", ""),
                "quiet": self.extra.get("quiet", False), "interests": self.extra.get("interests", []),
                "sealed": self.sealed}

    def parsed(self):
        return bc.parse_beacon(self.raw(), self.login, ttl_days=90)


# --------------------------------------------------------------------------- the crypto
def test_sealed_boxes_open_only_for_their_recipient_and_all_look_alike():
    a_priv, a_pub = sc.new_keypair()
    b_priv, _ = sc.new_keypair()
    short, long_ = sc.seal(a_pub, b'{"type":"thanks"}'), sc.seal(a_pub, b'{"type":"used","repo":"x/' + b"y" * 90 + b'"}')
    assert len(short) == len(long_) == sc.BOX_LEN          # the kind of signal can't be guessed from its size
    assert sc.open_box(a_priv, short) == b'{"type":"thanks"}'
    assert sc.open_box(b_priv, short) is None              # anyone else: nothing
    tampered = short[:60] + ("A" if short[60] != "A" else "B") + short[61:]
    assert sc.open_box(a_priv, tampered) is None
    assert sc.open_box(a_priv, "garbage") is None and sc.open_box(a_priv, None) is None


# --------------------------------------------------------------------------- parsing untrusted beacons
def test_parse_v2_keeps_only_valid_keys_and_boxes():
    alice = Person("alice", interests=["gwas", "<img src=x>"], status="hacked")
    _, me_pub = sc.new_keypair()
    alice.send(me_pub, "me", "thanks")
    raw = alice.raw()
    raw["keys"] += ["not-a-key", 5]
    raw["sealed"] += [{"at": NOW.date().isoformat(), "box": "short"}, "x",
                      {"at": "2020-01-01", "box": alice.sealed[0]["box"]}]       # expired
    parsed = bc.parse_beacon(raw, "alice", ttl_days=90)
    assert parsed["keys"] == [alice.pub] and len(parsed["sealed"]) == 1
    assert parsed["status"] == "" and parsed["interests"] == ["gwas"]


def test_parse_v1_still_reads_older_beacons():
    at = NOW.isoformat()
    raw = _raw_v1([{"to": "me", "type": "wave", "at": at}, {"to": "me", "type": "insult", "at": at},
                   {"to": "me", "type": "kudos", "at": at}, {"to": "me", "type": "kudos", "repo": "me/t", "at": at}])
    parsed = bc.parse_beacon(raw, "alice", ttl_days=90, now=NOW)
    assert [(g["type"], g.get("repo")) for g in parsed["gestures"]] == [("wave", None), ("kudos", "me/t")]
    assert parsed["keys"] == []      # can't receive private signals until they update


@pytest.mark.parametrize("raw", [None, [], "x", {"mygeeky_beacon": 3}, {"gestures": []}])
def test_parse_beacon_rejects_non_beacons(raw):
    assert bc.parse_beacon(raw, "alice", ttl_days=90, now=NOW) is None


def test_parse_beacon_owner_comes_from_repo_not_file():
    raw = Person("x").raw() | {"owner": "someone-else"}
    assert bc.parse_beacon(raw, "alice", ttl_days=90)["owner"] == "alice"
    assert bc.parse_beacon(raw, "bad/owner", ttl_days=90) is None


# --------------------------------------------------------------------------- receiving
def test_only_the_recipient_reads_a_signal_and_a_copied_box_is_rejected():
    me_priv, me_pub = sc.new_keypair()
    alice, mallory = Person("alice"), Person("mallory")
    alice.send(me_pub, "me", "thanks")
    alice.send(me_pub, "me", "used", repo="me/tool")
    alice.send(me_pub, "someone", "learn")          # sealed to my key but meant for someone else
    got = bc.open_signals(alice.parsed(), "me", me_priv, 90)
    assert [(g["type"], g.get("repo")) for g in got] == [("thanks", None), ("used", "me/tool")]
    other_priv, _ = sc.new_keypair()
    assert bc.open_signals(alice.parsed(), "me", other_priv, 90) == []   # a stranger opens nothing
    mallory.sealed = list(alice.sealed)             # mallory copies alice's boxes into her own beacon
    assert bc.open_signals(mallory.parsed(), "me", me_priv, 90) == []


def _cache(*people):
    return {"fetched_at": None,
            "users": {p.login: {"pushed_at": "", "avatar_url": "", "raw": p.raw()} for p in people}}


def test_collaborate_is_only_shown_when_both_chose_it():
    cfg = _cfg()
    me_priv, me_pub = bc.my_keypair("me")
    alice = Person("alice")
    alice.send(me_pub, "me", "collab")
    alice.send(me_pub, "me", "thanks")
    cache = _cache(alice)
    rows = bc.inbox(cache, cfg, bc.empty_beacon(), me_priv)
    assert [r["type"] for r in rows] == ["thanks"]                        # her 🤝 stays hidden...
    assert "no reply" not in rows[0]["text"] and not rows[0]["mutual"]
    mine = bc.add_signal(bc.empty_beacon(), "me", "alice", "collab", None, cfg, alice.parsed())
    rows = bc.inbox(cache, cfg, mine, me_priv)                            # ...until I choose it too
    match = next(r for r in rows if r["type"] == "collab")
    assert match["mutual"] and match["text"] == bc.MUTUAL_TEXT


def test_muted_and_blocked_people_are_hidden():
    me_priv, me_pub = bc.my_keypair("me")
    alice, troll = Person("alice"), Person("troll")
    alice.send(me_pub, "me", "thanks")
    troll.send(me_pub, "me", "thanks")
    cache = _cache(alice, troll)
    assert {r["from"] for r in bc.inbox(cache, _cfg(), bc.empty_beacon(), me_priv)} == {"alice", "troll"}
    assert {r["from"] for r in bc.inbox(cache, _cfg(beacon_muted=["Troll"]), bc.empty_beacon(), me_priv)} == {"alice"}
    assert {p["login"] for p in bc.people(cache, _cfg(beacon_blocked=["troll"]), bc.empty_beacon(),
                                          private_key=me_priv)} == {"alice"}


# --------------------------------------------------------------------------- sending, with courtesy
def test_add_signal_seals_for_every_key_of_the_recipient():
    cfg = _cfg()
    alice = Person("alice")
    second_priv, second_pub = sc.new_keypair()            # alice's laptop
    rec = dict(alice.parsed(), keys=[alice.pub, second_pub])
    b = bc.add_signal(bc.empty_beacon(), "me", "alice", "thanks", None, cfg, rec, now=NOW)
    entry = b["sent"][0]
    assert len(entry["boxes"]) == 2
    for priv, box in zip((alice.priv, second_priv), entry["boxes"]):
        msg = json.loads(sc.open_box(priv, box))
        assert (msg["from"], msg["to"], msg["type"]) == ("me", "alice", "thanks")


def test_courtesy_rules():
    cfg = _cfg(beacon_daily_limit=3, beacon_weekly_new_people=2, beacon_blocked=["troll"])
    people = {n: Person(n) for n in ("a1", "a2", "a3", "troll")}
    rec = lambda n: people[n].parsed()  # noqa: E731
    b = bc.add_signal(bc.empty_beacon(), "me", "a1", "thanks", None, cfg, rec("a1"), now=NOW)
    with pytest.raises(bc.BeaconError, match="already sent a1"):          # once a month is enough
        bc.add_signal(b, "me", "a1", "thanks", None, cfg, rec("a1"), now=NOW + timedelta(days=3))
    b = bc.add_signal(b, "me", "a1", "learn", None, cfg, rec("a1"), now=NOW)   # a different kind is fine
    b = bc.add_signal(b, "me", "a2", "thanks", None, cfg, rec("a2"), now=NOW)
    with pytest.raises(bc.BeaconError, match="signals today"):
        bc.add_signal(b, "me", "a1", "watching", None, cfg, rec("a1"), now=NOW)
    with pytest.raises(bc.BeaconError, match="new people this week"):
        bc.add_signal(b, "me", "a3", "thanks", None, cfg, rec("a3"), now=NOW + timedelta(days=1))
    bc.add_signal(b, "me", "a3", "thanks", None, cfg, rec("a3"), now=NOW + timedelta(days=8))  # next week
    bc.add_signal(b, "me", "a1", "thanks", None, cfg, rec("a1"), now=NOW + timedelta(days=31))
    with pytest.raises(bc.BeaconError, match="blocked"):
        bc.add_signal(bc.empty_beacon(), "me", "troll", "thanks", None, cfg, rec("troll"), now=NOW)


def test_quiet_old_or_unknown_recipients_get_nothing():
    cfg = _cfg()
    with pytest.raises(bc.BeaconError, match="isn't taking signals"):
        bc.add_signal(bc.empty_beacon(), "me", "q", "thanks", None, cfg, Person("q", quiet=True).parsed())
    old = bc.parse_beacon(_raw_v1([]), "old", ttl_days=90)
    with pytest.raises(bc.BeaconError, match="older myGeeKy"):
        bc.add_signal(bc.empty_beacon(), "me", "old", "thanks", None, cfg, old)
    with pytest.raises(bc.BeaconError, match="isn't on myGeeKy Signals"):
        bc.add_signal(bc.empty_beacon(), "me", "nobody", "thanks", None, cfg, None)
    for args in [("me", "thanks", None), ("alice", "hug", None), ("not valid!", "thanks", None),
                 ("alice", "used", None)]:
        with pytest.raises(bc.BeaconError):
            bc.add_signal(bc.empty_beacon(), "me", *args, cfg, Person("alice").parsed())


def test_public_beacon_reveals_nothing_about_who_was_signalled():
    cfg = _cfg(topics=["GWAS"], keywords=["fine mapping"], beacon_status="open-to-collab")
    _, my_pub = bc.my_keypair("me")
    alice = Person("alice")
    b = bc.add_signal(bc.empty_beacon(), "me", "alice", "thanks", None, cfg, alice.parsed())
    pub = bc.public_beacon(b, cfg, my_pub)
    assert set(pub) == {"mygeeky_beacon", "keys", "status", "quiet", "interests", "sealed"}
    text = json.dumps(pub)
    assert "alice" not in text and "thanks" not in text                     # who and what stay sealed
    assert pub["keys"] == [my_pub] and set(pub["interests"]) == {"gwas", "fine mapping"}
    assert len(pub["sealed"]) == 1 and len(pub["sealed"][0]["at"]) == 10   # only the day
    assert bc.public_beacon(b, _cfg(topics=["gwas"], beacon_share_interests=False), my_pub)["interests"] == []


def test_publishing_keeps_your_other_computers_keys_and_signals():
    cfg = _cfg()
    _, my_pub = bc.my_keypair("me")
    _, laptop_pub = sc.new_keypair()
    alice = Person("alice")
    laptop = Person("me")
    laptop.send(alice.pub, "alice", "learn")
    remote = {"mygeeky_beacon": 2, "keys": [laptop_pub], "sealed": laptop.sealed}
    b = bc.add_signal(bc.empty_beacon(), "me", "alice", "thanks", None, cfg, alice.parsed())
    pub = bc.public_beacon(b, cfg, my_pub, remote)
    assert pub["keys"] == [my_pub, laptop_pub] and len(pub["sealed"]) == 2
    # taking back the laptop's signal from here sticks, even though the laptop published it
    b = {**b, "withdrawn": [{"id": bc._box_id(laptop.sealed[0]["box"]), "at": datetime.now(timezone.utc).isoformat()}]}
    assert len(bc.public_beacon(b, cfg, my_pub, remote)["sealed"]) == 1


def test_old_local_history_is_kept_privately():
    from mygeeky.config import MY_BEACON_FILE
    MY_BEACON_FILE.parent.mkdir(parents=True, exist_ok=True)
    MY_BEACON_FILE.write_text(json.dumps(_raw_v1([{"to": "alice", "type": "wave", "at": NOW.isoformat()}])))
    mine = bc.load_my_beacon()
    assert mine["mygeeky_beacon"] == 2 and mine["sent"][0]["to"] == "alice" and "gestures" not in mine


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
        if self.put_status in (200, 201) and url.endswith("beacon.json"):
            self.existing = {"sha": "s", "content": json["content"]}
        return _FakeResp(self.put_status)


def test_writer_only_writes_its_own_beacon_repo():
    session = _FakeSession()
    w = bc.BeaconWriter("tok", "me", session=session)
    w.publish({"mygeeky_beacon": 2, "sealed": []})
    method, url, body = session.calls[-1]
    assert method == "PUT"
    assert url == "https://api.github.com/repos/me/mygeeky-beacon/contents/beacon.json"
    assert json.loads(base64.b64decode(body["content"]))["mygeeky_beacon"] == 2
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
    session = _FakeSession(existing=dict(existing))
    bc.BeaconWriter("tok", "me", session=session).publish({"a": 2})
    assert session.calls[-1][2]["sha"] == "abc"


def test_writer_explains_a_refused_token():
    with pytest.raises(bc.BeaconError, match="Contents: Read and write"):
        bc.BeaconWriter("tok", "me", session=_FakeSession(put_status=403)).publish({})


def test_send_publishes_before_saving_locally_and_unsend_takes_it_back():
    cfg = _cfg()
    alice = Person("alice")
    cache = _cache(alice)
    with pytest.raises(bc.BeaconError):
        bc.send(cfg, "alice", "thanks", writer=bc.BeaconWriter("t", "me", session=_FakeSession(put_status=403)),
                cache=cache)
    assert bc.load_my_beacon()["sent"] == []  # nothing recorded as sent
    session = _FakeSession()
    bc.send(cfg, "alice", "thanks", writer=bc.BeaconWriter("t", "me", session=session), cache=cache)
    assert [g["to"] for g in bc.load_my_beacon()["sent"]] == ["alice"]
    published = json.loads(base64.b64decode(session.existing["content"]))
    assert len(published["sealed"]) == 1 and "alice" not in json.dumps(published)
    assert bc.unsend(cfg, "alice", writer=bc.BeaconWriter("t", "me", session=session)) == 1
    assert bc.load_my_beacon()["sent"] == []
    assert json.loads(base64.b64decode(session.existing["content"]))["sealed"] == []


def test_send_requires_setup():
    with pytest.raises(bc.BeaconError, match="beacon init"):
        bc.send(MyGeekyConfig(github_username="me"), "alice", "thanks")


def test_ensure_published_adds_this_computers_key_once():
    cfg = _cfg()
    session = _FakeSession()
    w = bc.BeaconWriter("t", "me", session=session)
    assert bc.ensure_published(cfg, w) is True
    published = json.loads(base64.b64decode(session.existing["content"]))
    assert published["keys"] == [bc.my_keypair("me")[1]]
    assert bc.ensure_published(cfg, w) is False        # already there: no more writes


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


def test_refresh_inbox_and_people():
    recent = datetime.now(timezone.utc).isoformat()
    me_priv, me_pub = bc.my_keypair("me")
    alice = Person("alice", interests=["gwas"])
    alice.send(me_pub, "me", "thanks")
    alice.send(me_pub, "me", "used", repo="me/tool")
    bob = Person("bob", status="mentoring", interests=["rust"])
    client = _FakeClient(
        [_repo("alice"), _repo("bob"), _repo("me"), _repo("org", typ="Organization"),
         _repo("carol", name="other-repo"), _repo("old")],
        {"alice": alice.raw(), "bob": bob.raw(),
         "old": _raw_v1([{"to": "me", "type": "wave", "at": recent}])})
    cfg = _cfg(topics=["gwas"])
    cache = bc.refresh(client, cfg, force=True)
    assert set(cache["users"]) == {"alice", "bob", "old"}   # self, orgs, other repos skipped

    rows = bc.inbox(cache, cfg, bc.empty_beacon(), me_priv)
    assert {(r["from"], r["type"]) for r in rows} == {("alice", "thanks"), ("alice", "used"), ("old", "wave")}
    assert "used me/tool in their work" in next(r for r in rows if r["type"] == "used")["text"]
    assert not any(r["mutual"] for r in rows)

    ppl = bc.people(cache, cfg, bc.empty_beacon(), private_key=me_priv)
    assert [p["login"] for p in ppl][:2] == ["alice", "old"]       # signalled you first
    assert ppl[0]["shared"] == ["gwas"] and ppl[0]["can_receive"]
    assert next(p for p in ppl if p["login"] == "old")["can_receive"] is False
    assert next(p for p in ppl if p["login"] == "bob")["status"] == bc.STATUSES["mentoring"]

    # unchanged repos are reused from the cache, not fetched again
    client.fetched.clear()
    bc.refresh(client, cfg, force=True)
    assert client.fetched == []


def test_refresh_respects_interval():
    cfg = _cfg(beacon_refresh_minutes=30)
    client = _FakeClient([_repo("alice")], {"alice": Person("alice").raw()})
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
    me_priv, me_pub = bc.my_keypair("me")
    newbie = Person("newbie")
    newbie.send(me_pub, "me", "thanks")
    client = _FakeClient([_repo("alice")], {"alice": Person("alice").raw(), "newbie": newbie.raw()},
                         by_name=[_repo("alice"), _repo("newbie"), _repo("copycat", name="not-mygeeky-beacon"),
                                  dict(_repo("secret"), private=True)])
    cfg = _cfg()
    cache = bc.refresh(client, cfg, force=True)
    assert set(cache["users"]) == {"alice", "newbie"}
    assert [r["from"] for r in bc.inbox(cache, cfg, bc.empty_beacon(), me_priv)] == ["newbie"]


def test_beacon_init_walks_through_repo_and_token_and_retries_a_bad_token(monkeypatch):
    from click.testing import CliRunner

    import mygeeky.cli as cli
    from mygeeky.config import save_config

    save_config(MyGeekyConfig(github_username="me"))
    from mygeeky import token_check
    monkeypatch.setattr(token_check, "check", lambda *a, **kw: {"ok": True, "errors": [], "warnings": [],
                                                                "summary": ""})
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
