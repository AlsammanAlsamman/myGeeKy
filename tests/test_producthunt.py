from datetime import datetime, timedelta, timezone

import pytest

from mygeeky import producthunt as ph
from mygeeky.config import MyGeekyConfig


def _node(slug, votes=10, name="Tool", tagline="does things", topics=("Developer Tools",), **kw):
    return {"slug": slug, "name": name, "tagline": tagline, "description": kw.get("description", ""),
            "votesCount": votes, "commentsCount": 2, "createdAt": "2026-10-01T07:00:00Z",
            "thumbnail": {"url": kw.get("thumb", "https://ph-files.imgix.net/x.png")},
            "topics": {"edges": [{"node": {"name": t, "slug": t.lower()}} for t in topics]}}


def test_clean_post_validates_and_rebuilds_link():
    p = ph.clean_post(_node("cool-tool", name="  Cool\n Tool ", thumb="javascript:alert(1)"))
    assert p["url"] == "https://www.producthunt.com/posts/cool-tool"
    assert p["name"] == "Cool Tool" and p["thumbnail"] == ""
    for bad in (_node("../../evil"), _node("Has Space"), {"slug": "ok", "votesCount": "lots"}, None, "x"):
        assert ph.clean_post(bad) is None
    assert len(ph.clean_post(_node("long", tagline="x" * 1000))["tagline"]) == 140


def test_rank_puts_your_field_first_then_votes():
    posts = [ph.clean_post(n) for n in (
        _node("popular", votes=900),
        _node("gwas-viewer", votes=40, tagline="Interactive GWAS manhattan plots"),
        _node("seq-kit", votes=60, description="Single-cell and GWAS pipelines"),
        _node("meh", votes=5),
    )]
    ranked = ph.rank(posts, ["gwas", "single-cell"], size=3)
    assert [p["slug"] for p in ranked] == ["seq-kit", "gwas-viewer", "popular"]
    assert ranked[0]["match"] == ["gwas", "single-cell"] and ranked[2]["match"] == []


class _Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body or {}

    def json(self):
        return self._body


class _Session:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def post(self, url, headers, timeout, json):
        assert url == ph.API and headers["Authorization"] == "Bearer tok"
        self.calls.append(json["variables"])
        return self.pages.pop(0)


def _page(nodes, next_cursor=None):
    return _Resp(200, {"data": {"posts": {"edges": [{"node": n} for n in nodes],
                                          "pageInfo": {"hasNextPage": bool(next_cursor), "endCursor": next_cursor}}}})


def test_fetch_posts_pages_dedupes_and_skips_bad_topics():
    session = _Session([
        _page([_node("a"), _node("b")], next_cursor="c1"),
        _page([_node("b"), _node("c")]),
        _Resp(200, {"errors": [{"message": "Topic not found"}]}),
    ])
    logs = []
    posts = ph.fetch_posts("tok", ["developer-tools", "nope"], days=30, session=session, log=logs.append)
    assert sorted(p["slug"] for p in posts) == ["a", "b", "c"]
    assert session.calls[1]["cursor"] == "c1"
    assert "Topic not found" in logs[0]


def test_fetch_posts_reports_a_refused_token():
    with pytest.raises(ph.ProductHuntError, match="auth producthunt"):
        ph.fetch_posts("tok", ["developer-tools"], days=30, session=_Session([_Resp(401)]))


def test_refresh_respects_interval_and_computes_terms_lazily():
    cfg = MyGeekyConfig(market_ph_topics=["developer-tools"], market_refresh_hours=12, market_ph_size=5)
    asked = []
    terms = lambda: asked.append(1) or ["gwas"]  # noqa: E731
    state = ph.refresh(cfg, "tok", terms, session=_Session([_page([_node("gwas-tool", tagline="GWAS")])]))
    assert state["posts"][0]["slug"] == "gwas-tool" and asked == [1]
    ph.refresh(cfg, "tok", terms, session=_Session([]))  # not due: no request, no profile work
    assert asked == [1]
    later = datetime.now(timezone.utc) + timedelta(hours=13)
    assert ph.refresh_due(cfg, ph.load_state(), now=later)


def test_product_hunt_row_is_plain_text_and_opens_only_allowed_links():
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLabel

    from mygeeky.gui import app as logic
    from mygeeky.gui.app import THEMES
    from mygeeky.gui.qt_panel import ProductHuntRow

    QApplication.instance() or QApplication([])
    post = dict(ph.clean_post(_node("x", name="<b>Bold</b>", tagline="GWAS")), match=["gwas"])
    opened = []
    row = ProductHuntRow(post, THEMES["midnight"], opened.append)
    name = next(lbl for lbl in row.findChildren(QLabel) if lbl.text() == "<b>Bold</b>")
    assert name.textFormat() == Qt.PlainText
    assert any(lbl.text() == "your field" for lbl in row.findChildren(QLabel))
    row.mousePressEvent(None)
    assert opened == ["https://www.producthunt.com/posts/x"]
    assert logic.open_link("https://evil.example.com/") is False
    assert logic.open_link("https://www.producthunt.com/admin") is False
