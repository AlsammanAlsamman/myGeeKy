from mygeeky.activity import format_event, get_recent_activity


def test_format_event_push():
    event = {
        "type": "PushEvent",
        "actor": {"login": "friend1", "avatar_url": "https://example.com/a.png"},
        "repo": {"name": "friend1/tool"},
        "payload": {"size": 3},
        "created_at": "2026-09-17T10:00:00Z",
    }
    record = format_event(event)
    assert record["actor"] == "friend1"
    assert record["verb"] == "pushed 3 commits"
    assert record["repo"] == "friend1/tool"
    assert record["repo_url"] == "https://github.com/friend1/tool"
    assert record["profile_url"] == "https://github.com/friend1"


def test_format_event_merged_pull_request():
    event = {
        "type": "PullRequestEvent",
        "actor": {"login": "friend2", "avatar_url": ""},
        "repo": {"name": "org/repo"},
        "payload": {"action": "closed", "pull_request": {"merged": True}},
        "created_at": "2026-09-17T10:00:00Z",
    }
    record = format_event(event)
    assert record["verb"] == "merged a pull request"


def test_format_event_unknown_type_returns_none():
    assert format_event({"type": "SomeFutureEventType", "actor": {}, "repo": {}, "payload": {}}) is None


def test_format_event_malformed_payload_returns_none():
    # PushEvent formatter expects payload to behave like a dict; a string
    # payload should be handled gracefully rather than raising.
    event = {"type": "PushEvent", "actor": {"login": "x"}, "repo": {"name": "x/y"}, "payload": "not-a-dict"}
    assert format_event(event) is None


class FakeClient:
    def __init__(self, events):
        self.events = events

    def list_received_events(self, username, per_page=30):
        return self.events


def test_get_recent_activity_filters_and_limits():
    events = [
        {"type": "PushEvent", "actor": {"login": "a"}, "repo": {"name": "a/x"}, "payload": {"size": 1}, "created_at": "t"},
        {"type": "UnknownEvent", "actor": {"login": "b"}, "repo": {"name": "b/x"}, "payload": {}, "created_at": "t"},
        {"type": "WatchEvent", "actor": {"login": "c"}, "repo": {"name": "c/x"}, "payload": {}, "created_at": "t"},
    ]
    client = FakeClient(events)
    result = get_recent_activity(client, "me", limit=1)
    assert len(result) == 1
    assert result[0]["actor"] == "a"
