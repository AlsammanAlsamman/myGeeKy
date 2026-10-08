from datetime import datetime, timedelta, timezone

import pytest

from mygeeky import headlines as hl
from mygeeky.config import MyGeekyConfig

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
NATURE = next(f for f in hl.FEEDS if f[0] == "nature")
REGISTER = next(f for f in hl.FEEDS if f[0] == "register")

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Genome accessibility reveals disease risk</title><link>https://www.nature.com/articles/a1</link>
  <pubDate>Wed, 07 Oct 2026 10:00:00 GMT</pubDate><description>&lt;p&gt;GWAS &amp;amp; chromatin&lt;/p&gt;</description></item>
<item><title>ChatGPT&amp;#8217;s new UI</title><link>https://www.nature.com/articles/a2</link>
  <pubDate>Wed, 07 Oct 2026 09:00:00 GMT</pubDate></item>
<item><title>Phishing link</title><link>https://evil.example.com/x</link><pubDate>Wed, 07 Oct 2026 09:00:00 GMT</pubDate></item>
<item><title>No date</title><link>https://www.nature.com/articles/a3</link></item>
<item><title>Not https</title><link>http://www.nature.com/articles/a4</link><pubDate>Wed, 07 Oct 2026 09:00:00 GMT</pubDate></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Windows Search learns to take orders</title>
  <link rel="alternate" href="https://www.theregister.com/2026/10/08/windows/"/>
  <updated>2026-10-08T08:00:00Z</updated></entry>
</feed>"""


def test_parse_rss_and_atom_keep_only_safe_dated_titles():
    items = hl.parse_feed(RSS, NATURE)
    assert [x["title"] for x in items] == ["Genome accessibility reveals disease risk", "ChatGPT’s new UI"]
    assert items[0]["summary"] == "GWAS & chromatin"          # tags dropped, double-escaped entities decoded
    assert all(x["category"] == "science" and x["source"] == "Nature" for x in items)
    atom = hl.parse_feed(ATOM, REGISTER)
    assert atom[0]["link"].startswith("https://www.theregister.com/") and atom[0]["category"] == "tech"


def test_links_must_point_at_the_feeds_own_site():
    assert hl.allowed_link("https://www.nature.com/articles/x")
    assert not hl.allowed_link("https://www.nature.com.evil.io/x")
    assert not hl.allowed_link("https://user@www.nature.com/x")
    assert not hl.allowed_link("javascript:alert(1)")


def _item(i, title, category="science", hours=1):
    return {"id": f"id{i}", "title": title, "link": f"https://www.nature.com/{i}", "source": "Nature",
            "feed": "nature", "category": category, "published": (NOW - timedelta(hours=hours)).isoformat(),
            "summary": ""}


def test_your_model_picks_what_is_for_you_and_the_rest_is_the_big_picture():
    weights = {"gwas": 1.0, "fine mapping": 0.8, "genomics": 0.6, "link": 0.5}
    items = [_item(1, "New GWAS of 2 million people"),                 # your own keyword
             _item(2, "Fine mapping meets single-cell genomics"),      # a phrase + another term
             _item(3, "TP-Link sued over router security", "tech"),    # one stray CV word: not evidence
             _item(4, "A new open model beats GPT", "ai"),
             _item(5, "Old GWAS news", hours=24 * 9)]                  # too old
    cfg = MyGeekyConfig(headlines_size=4, headlines_ai_min=1, explore_share=0.25)
    picks = hl.select(items, cfg, weights, now=NOW)
    mine = [x["title"] for x in picks if not x["explore"]]
    wide = [x["title"] for x in picks if x["explore"]]
    assert set(mine) == {"New GWAS of 2 million people", "Fine mapping meets single-cell genomics"}
    assert "A new open model beats GPT" in wide and "TP-Link sued over router security" in wide
    assert "Old GWAS news" not in mine + wide
    assert all("summary" not in x for x in picks)                       # titles only


def test_always_a_few_ai_headlines_and_no_duplicates():
    weights = {"gwas": 1.0}
    items = [_item(i, f"GWAS study number {i}") for i in range(10)] + \
            [_item(20 + i, f"AI story {i}", "ai", hours=2 + i) for i in range(5)] + \
            [_item(40, "GWAS study number 1")]                          # same story from another feed
    cfg = MyGeekyConfig(headlines_size=6, headlines_ai_min=2, explore_share=0.0)
    picks = hl.select(items, cfg, weights, now=NOW)
    assert sum(1 for x in picks if x["category"] == "ai") >= 2
    titles = [x["title"] for x in picks]
    assert len(titles) == len(set(titles))


def test_refresh_survives_a_broken_feed(monkeypatch):
    cfg = MyGeekyConfig(headlines_categories=["science", "tech"])

    def fake_fetch(feed, session):
        if feed[0] == "nature":
            return hl.parse_feed(RSS, NATURE)
        raise TimeoutError("down")
    monkeypatch.setattr(hl, "fetch", fake_fetch)
    monkeypatch.setattr(hl.interests, "profile_terms", lambda cfg: {"genome accessibility": 1.0})
    state = hl.refresh(cfg, force=True)
    assert state["items"] and "Nature Genetics" in state["errors"]
    assert not any(e in ("OpenAI", "Hugging Face") for e in state["errors"])     # ai not asked for
    assert hl.refresh_due(cfg, hl.load_state()) is False


def test_news_tab_shows_headlines_grouped(monkeypatch):
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLabel
    QApplication.instance() or QApplication([])
    from mygeeky.gui import app as logic
    from mygeeky.gui.qt_panel import HeadlineRow, MyGeekyPanel

    for name, value in (("get_contributions", lambda cfg: []),
                        ("get_suggestions", lambda cfg: {"followback": [], "domain_highlights": []}),
                        ("get_activity", lambda cfg, force=False: {"events": []}),
                        ("get_model_history", lambda: []),
                        ("get_friend_stats", lambda cfg: {"total_friends": 0, "new_this_week": 0,
                                                          "follow_back_rate": None, "total_labeled": 0}),
                        ("get_headlines", lambda cfg: {"items": [
                            dict(_item(1, "<b>GWAS</b> news"), explore=False, match=["gwas"]),
                            dict(_item(2, "Big AI thing", "ai"), explore=True, match=[])]})):
        monkeypatch.setattr(logic, name, value)
    opened = []
    monkeypatch.setattr(logic, "open_link", lambda url: opened.append(url) or True)
    panel = MyGeekyPanel(MyGeekyConfig(github_username="me"))
    try:
        panel._load_news()
        from PySide6.QtCore import QCoreApplication, QEvent
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)   # rows from the first render go away
        rows = panel.headlines_box.findChildren(HeadlineRow)
        assert len(rows) == 2
        labels = [lbl.text() for lbl in panel.headlines_box.findChildren(QLabel)]
        assert "FOR YOUR WORK" in labels and any("BIG PICTURE" in t for t in labels)
        title = next(lbl for lbl in rows[0].findChildren(QLabel) if lbl.text() == "<b>GWAS</b> news")
        assert title.textFormat() == Qt.PlainText               # feed text is never rendered as HTML
        rows[0].mousePressEvent(None)
        assert opened == ["https://www.nature.com/1"]
        panel._set_news_mode("papers")
        assert panel.headlines_box.isHidden() and not panel.news_box.isHidden()
    finally:
        panel.ticker.stop()
        for t in (panel._activity_timer, panel._signals_timer, panel._update_timer, panel._news_timer,
                  panel._dock_guard, panel._sync_timer):
            t.stop()
        for w in list(panel._workers):
            w.wait(2000)
        panel.close()
        panel.deleteLater()
