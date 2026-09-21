import pytest

pytest.importorskip("PySide6", reason="PySide6 (the 'gui' extra) is not installed")

from mygeeky.gui.qt_panel import _build_spotlight_items


def test_build_spotlight_items_interleaves_activity_and_suggestions():
    activity = [
        {"actor": "a1", "actor_avatar": "u1", "profile_url": "p1", "verb": "pushed 2 commits",
         "repo": "a1/tool", "created_at": "2026-01-01T00:00:00Z"},
        {"actor": "a2", "actor_avatar": "u2", "profile_url": "p2", "verb": "starred the repo",
         "repo": "", "created_at": "2026-01-01T00:00:00Z"},
    ]
    suggestions = [
        {"username": "s1", "avatar_url": "su1", "profile_url": "sp1", "score": 0.81, "bio": "bio1"},
    ]

    items = _build_spotlight_items(activity, suggestions)

    assert [i["kind"] for i in items] == ["activity", "suggestion", "activity"]
    assert items[0]["username"] == "a1"
    assert "pushed 2 commits in a1/tool" == items[0]["headline"]
    assert items[1]["username"] == "s1"
    assert "0.81" in items[1]["headline"]
    assert items[2]["username"] == "a2"
    assert items[2]["headline"] == "starred the repo"  # no repo name -> no "in ..." suffix


def test_build_spotlight_items_empty_inputs():
    assert _build_spotlight_items([], []) == []
