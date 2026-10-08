"""One small letter, one meaning, everywhere in myGeeKy:

    P  green   a published paper    (an item that IS a paper; a repo that HAS one)
    N  yellow  news                 (a news story; a repo IN this week's news)
    D  blue    discussion           (a Hacker News thread; a repo discussed there)
    A  violet  announcement         (an AI lab's or company's own blog post)

Everything here works on what's already on disk (the News and Headlines
lists), so badges cost no network calls.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

BADGES: dict[str, tuple[str, str]] = {
    "P": ("paper", "#22c55e"),
    "N": ("news", "#eab308"),
    "D": ("discussion", "#38bdf8"),
    "A": ("announcement", "#a78bfa"),
}
ANNOUNCEMENT_FEEDS = {"openai", "google-ai", "deepmind", "huggingface", "github-blog"}
PAPER_FEEDS = {"nature-genetics", "nature-biotech"}          # research journals' own feeds
# Nature: /articles/s41586-... is a research paper, /articles/d41586-... is news
_NATURE_PAPER = re.compile(r"nature\.com/articles/s4\d{4}-")
# repo names too common to count as "this repo is in the news" from a title alone
COMMON_NAMES = {
    "tools", "awesome", "project", "projects", "models", "model", "python", "server", "client", "github",
    "engine", "agent", "agents", "react", "notes", "docs", "scripts", "utils", "core", "data", "pipeline",
    "pipelines", "website", "config", "dotfiles", "examples", "tutorial", "course", "paper", "papers",
    "research", "analysis", "workflow", "workflows", "library", "framework", "toolkit", "benchmark",
    "dataset", "datasets", "app", "api", "cli", "demo", "test", "tests", "source", "public", "release",
}


def item_kind(item: dict[str, Any]) -> str:
    """P, N, D or A for a News or Headlines item."""
    source = item.get("source", "")
    if source in ("arxiv", "biorxiv"):
        return "P"
    if source == "hackernews":
        return "D"
    feed = item.get("feed", "")
    if feed in ANNOUNCEMENT_FEEDS:
        return "A"
    if feed in PAPER_FEEDS or _NATURE_PAPER.search(item.get("link", "")):
        return "P"
    return "N"


def _distinctive(name: str) -> bool:
    n = name.lower()
    if len(n) < 5 or n in COMMON_NAMES:
        return False
    try:
        from . import keywords
        if keywords.known(n):              # "genomics", "llm": a field, not a project
            return False
    except Exception:
        pass
    return True


def _name_pattern(name: str) -> re.Pattern:
    words = [re.escape(w) for w in re.split(r"[-_.]+", name) if w]
    return re.compile(r"(?<![\w/])" + r"[\s_.-]?".join(words) + r"(?![\w])", re.I)


def in_the_news(repos: Iterable[str], items: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """{owner/name: the newest story about it} -- a story links to the repo on
    GitHub, or names a distinctive repo in its title. Kind N (news) beats D."""
    items = list(items)
    found: dict[str, dict[str, Any]] = {}
    for repo in repos:
        if not repo or "/" not in repo:
            continue
        owner, name = repo.split("/", 1)
        gh = f"github.com/{repo}".lower()
        pattern = _name_pattern(name) if _distinctive(name) else None
        for it in items:
            links = " ".join(str(it.get(k) or "") for k in ("link", "url", "story_url")).lower()
            title = it.get("title", "")
            if gh in links or (pattern and pattern.search(title)):
                kind = "D" if it.get("source") == "hackernews" else "N"
                story = {"kind": kind, "title": title, "source": it.get("source_label") or it.get("source", ""),
                         "url": it.get("link") or it.get("url", ""), "published": it.get("published", "")}
                best = found.get(repo)
                if best is None or (best["kind"] == "D" and kind == "N") or \
                        (best["kind"] == kind and story["published"] > best["published"]):
                    found[repo] = story
    return found
