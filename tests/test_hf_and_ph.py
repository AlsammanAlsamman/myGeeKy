import pytest

from mygeeky import hfmodels as hf
from mygeeky import producthunt as ph
from mygeeky.config import MyGeekyConfig


def _m(i, **kw):
    return {"id": f"org/model-{i}", "likes": kw.get("likes", 10), "downloads": 100, "trendingScore": kw.get("trend", 5),
            "pipeline_tag": kw.get("pipeline", "text-generation"), "tags": kw.get("tags", []), "createdAt": "2026-10-01"}


def test_clean_validates_ids_and_rebuilds_links():
    assert hf.clean(_m(1))["url"] == "https://huggingface.co/org/model-1"
    assert hf.clean({"id": "../../etc/passwd"}) is None
    assert hf.clean({"id": "javascript:alert(1)/x"}) is None
    bad_tag = hf.clean({**_m(2), "tags": ["ok-tag", "<script>", 5]})
    assert bad_tag["tags"] == ["ok-tag"]


def test_field_tags_follow_your_interests():
    tags = hf.field_tags({"gwas": 1.0, "single cell": 0.8, "protein": 0.5, "python": 0.4}, extra=[])
    assert tags[0] == "biology" and "genomics" in tags and "protein" in tags
    assert hf.field_tags({}, extra=["Fine Mapping"]) == ["fine-mapping"]       # your own keyword, as a tag


class FakeSession:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(params)

        class R:
            def raise_for_status(self_inner):
                pass

            def json(self_inner):
                if params.get("filter") == "biology":
                    return [_m(1, tags=["biology", "single-cell"], trend=3), _m(2, trend=0, likes=2),   # junk upload
                            _m(3, tags=["biology"], trend=40, likes=900)]
                if params.get("filter"):
                    return []
                return [_m(3, trend=40), _m(9, trend=2000, likes=5000)]                # global trending
        return R()


def test_refresh_in_your_field_then_trending_everywhere(monkeypatch):
    monkeypatch.setattr(hf.interests, "profile_terms", lambda cfg: {"single cell": 1.0, "gene": 0.8})
    session = FakeSession()
    state = hf.refresh(MyGeekyConfig(market_hf_size=5), force=True, session=session)
    ids = [m["id"] for m in state["field"]]
    assert "org/model-2" not in ids                                 # no trending score, few likes: skipped
    assert set(ids) == {"org/model-1", "org/model-3"}
    assert next(m for m in state["field"] if m["id"] == "org/model-1")["match"] == ["single cell"]
    assert [m["id"] for m in state["trending"]] == ["org/model-9"]  # already shown above: not repeated
    assert any(c.get("filter") == "biology" for c in session.calls)
    assert hf.refresh_due(MyGeekyConfig(), hf.load_state()) is False


FEED = b"""<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>GeneLens</title><published>2026-10-08T06:00:00-07:00</published>
  <link rel="alternate" type="text/html" href="https://www.producthunt.com/products/genelens"/>
  <content type="html">&lt;p&gt; A copilot for single cell &amp;amp; GWAS analysis &lt;/p&gt;&lt;p&gt;&lt;a href="x"&gt;Discussion&lt;/a&gt;&lt;/p&gt;</content></entry>
<entry><title>Evil</title><link rel="alternate" href="https://evil.example.com/products/x"/><content type="html"></content></entry>
</feed>"""


def test_product_hunt_works_without_a_token(monkeypatch):
    class S:
        def get(self, url, timeout=None, headers=None):
            class R:
                content = FEED

                def raise_for_status(self_inner):
                    pass
            return R()
    posts = ph.fetch_feed(S())
    assert [p["name"] for p in posts] == ["GeneLens"]
    assert posts[0]["tagline"] == "A copilot for single cell & GWAS analysis"
    assert posts[0]["url"] == "https://www.producthunt.com/products/genelens" and posts[0]["from_feed"]
    ranked = ph.rank(posts, ["gwas", "r"], 10)
    assert ranked[0]["match"] == ["gwas"]                            # "r" alone never counts


def test_market_models_view(monkeypatch):
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from mygeeky.gui import app as logic
    from mygeeky.gui.qt_panel import ModelRow, MyGeekyPanel

    model = {**hf.clean(_m(1, tags=["biology"])), "match": ["single cell"]}
    for name, value in (("get_contributions", lambda cfg: []),
                        ("get_suggestions", lambda cfg: {"followback": [], "domain_highlights": []}),
                        ("get_activity", lambda cfg, force=False: {"events": []}),
                        ("get_model_history", lambda: []),
                        ("get_friend_stats", lambda cfg: {"total_friends": 0, "new_this_week": 0,
                                                          "follow_back_rate": None, "total_labeled": 0}),
                        ("get_hf_models", lambda cfg: {"field": [model], "trending": [dict(model, id="x/y")],
                                                       "tags": ["biology"], "updated_at": None}),
                        ("hf_models_due", lambda cfg: False)):
        monkeypatch.setattr(logic, name, value)
    opened = []
    monkeypatch.setattr(logic, "open_link", lambda url: opened.append(url) or True)
    panel = MyGeekyPanel(MyGeekyConfig(github_username="me"))
    try:
        assert "models" in panel.market_mode_buttons
        panel._set_market_mode("models")
        assert panel.market_stack.currentIndex() == 2
        rows = panel.models_area.parentWidget().findChildren(ModelRow)
        assert len(rows) == 2
        rows[0].mousePressEvent(None)
        assert opened == ["https://huggingface.co/org/model-1"]
    finally:
        panel.ticker.stop()
        for t in (panel._activity_timer, panel._signals_timer, panel._update_timer, panel._news_timer,
                  panel._dock_guard, panel._sync_timer):
            t.stop()
        for w in list(panel._workers):
            w.wait(2000)
        panel.close()
        panel.deleteLater()
