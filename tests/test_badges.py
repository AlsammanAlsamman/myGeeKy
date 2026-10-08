import pytest

from mygeeky import badges


@pytest.mark.parametrize("item, kind", [
    ({"source": "arxiv"}, "P"),
    ({"source": "biorxiv"}, "P"),
    ({"source": "hackernews"}, "D"),
    ({"source": "OpenAI", "feed": "openai"}, "A"),
    ({"source": "GitHub", "feed": "github-blog"}, "A"),
    ({"source": "Nature Genetics", "feed": "nature-genetics", "link": "https://www.nature.com/articles/s41588-026-1"}, "P"),
    ({"source": "Nature", "feed": "nature", "link": "https://www.nature.com/articles/s41586-026-1"}, "P"),
    ({"source": "Nature", "feed": "nature", "link": "https://www.nature.com/articles/d41586-026-1"}, "N"),
    ({"source": "ScienceDaily", "feed": "sciencedaily"}, "N"),
])
def test_every_item_gets_one_letter(item, kind):
    assert badges.item_kind(item) == kind


def test_a_repo_is_in_the_news_by_link_or_by_its_distinctive_name():
    items = [
        {"source": "Ars Technica", "title": "Why everyone is talking about uv", "link": "https://arstechnica.com/a",
         "published": "2026-10-07T00:00:00+00:00"},
        {"source": "hackernews", "title": "Show HN: a faster aligner", "url": "https://news.ycombinator.com/item?id=1",
         "story_url": "https://github.com/lh3/minimap2", "published": "2026-10-06T00:00:00+00:00"},
        {"source": "The Verge", "title": "Seurat 6 lands with spatial support", "link": "https://www.theverge.com/x",
         "published": "2026-10-07T00:00:00+00:00"},
        {"source": "The Register", "title": "New tools for awesome pipelines", "link": "https://www.theregister.com/y",
         "published": "2026-10-07T00:00:00+00:00"},
        {"source": "hackernews", "title": "Seurat discussion", "url": "https://news.ycombinator.com/item?id=2",
         "published": "2026-10-08T00:00:00+00:00"},
    ]
    found = badges.in_the_news(["lh3/minimap2", "satijalab/seurat", "sindresorhus/awesome", "me/tools", "x/uv"], items)
    assert found["lh3/minimap2"]["kind"] == "D"                       # linked from a Hacker News story
    assert found["satijalab/seurat"]["kind"] == "N"                   # news beats a later discussion
    assert "Seurat 6" in found["satijalab/seurat"]["title"]
    assert "sindresorhus/awesome" not in found and "me/tools" not in found   # too common to count
    assert "x/uv" not in found                                        # too short to count from a title


def test_a_field_name_is_not_a_project(monkeypatch):
    from mygeeky import keywords
    monkeypatch.setattr(keywords, "known", lambda w: w == "genomics")
    items = [{"source": "Nature", "title": "Genomics is booming", "link": "https://www.nature.com/d", "published": ""}]
    assert badges.in_the_news(["someone/genomics"], items) == {}


def test_badge_widgets(monkeypatch):
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from mygeeky.gui.qt_panel import letter_badge, news_badge, published_badge
    opened = []
    p = published_badge({"title": "A paper", "url": "https://doi.org/10.1/x", "cited": 3}, opened.append)
    n = news_badge({"kind": "N", "title": "Seurat 6 lands", "url": "https://www.theverge.com/x"}, opened.append)
    d = news_badge({"kind": "D", "title": "Show HN", "url": "https://news.ycombinator.com/item?id=1"}, opened.append)
    assert (p.text(), n.text(), d.text()) == ("P", "N", "D")
    assert "#eab308" in n.styleSheet() and "#22c55e" in p.styleSheet() and "Hacker News" in d.toolTip()
    n.click()
    assert opened == ["https://www.theverge.com/x"]
    assert letter_badge("A", "Announcement").text() == "A"
