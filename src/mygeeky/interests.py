"""What you're into lately -- learned from what you do -- and room to explore.

Every click on a person, repo, Market row or news item, every new follow,
star or fork becomes an *interest event*: a handful of terms pulled from that
item (its topics, description, bio, title), never the item's full text.
Events fade with a half-life (`interest_half_life_days`), so the profile
follows you as your work moves on.

The learned terms feed back into everything: the search terms that pick
people, repos to contribute to and the Market watchlist (contribute.search_terms),
the ranking of suggestions and repos, and the News.

So it doesn't shut you in a bubble, every list keeps `explore_share` of its
places (20% by default) for things *outside* your usual interests -- "new
territory", marked 🔭 -- found through rotating exploration terms. Clicking
one teaches myGeeKy that the new area interests you too.

Events live in interest_events.jsonl (synced to your private data repo, so
every machine learns from all of them). Turn learning off with
`mygeeky config set interest_learning false`.
"""

from __future__ import annotations

import json
import math
import random
import re
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import CV_TEXT_FILE, INTEREST_EVENTS_FILE, MyGeekyConfig, ensure_dirs

# how much one action says about your interests
KIND_WEIGHTS = {
    "fork": 2.5,
    "follow": 2.0,
    "star": 1.5,
    "repo": 1.0,      # clicked a repo (Repos, Market)
    "news": 0.8,
    "person": 0.7,    # clicked a suggested person
}
TERMS_PER_EVENT = 12
MIN_LEARNED_WEIGHT = 1.0   # one stray click shouldn't redirect anything

STOPWORDS = set("""
a about above after again all also am an and any are as at be because been before being below between both but by
can could did do does doing down during each few for from further had has have having he her here hers him his how
i if in into is it its itself just like more most my no nor not now of off on once only or other our out over own
same she should so some such than that the their them then there these they this those through to too under until
up very was we were what when where which while who whom why will with would you your yours new using use used based
via based tool tools library framework project projects repository repo code app apps simple fast easy small
open source github python data analysis software package packages implementation official awesome list lists
paper papers study studies results method methods approach approaches work works model models system systems
first make makes made build built support supports supported way well one two three version release released
analysis analyses associated association different various several including include includes high low large
show shows shown found among within across however therefore also used provide provides provided
toolkit toolkits toolbox utility utilities wrapper wrappers helper helpers module modules plugin plugins
""".split())

# Broad fields to wander into; today's picks rotate daily and skip what you already follow
EXPLORE_POOL = [
    "single-cell", "spatial transcriptomics", "protein design", "llm agents", "causal inference",
    "graph neural networks", "reproducibility", "data visualization", "rust", "webassembly",
    "privacy", "climate", "epidemiology", "microscopy", "robotics", "quantum computing",
    "open science", "bayesian", "time series", "drug discovery", "metagenomics", "neuroscience",
    "computer vision", "education", "accessibility", "high performance computing", "ecology",
    "statistics", "knowledge graphs", "workflow management",
]

_WORD = re.compile(r"[a-z][a-z0-9+#.\-]{2,}")


def extract_terms(text: str = "", topics: Iterable[str] = ()) -> dict[str, float]:
    """The item's topics (whole) plus its most telling words, weighted to sum to 1."""
    counts: Counter[str] = Counter()
    for t in topics or ():
        t = str(t).strip().lower().replace("-", " ")
        if 2 < len(t) <= 40:
            counts[t] += 3
    for w in _WORD.findall((text or "").lower()):
        w = w.strip(".-").replace("-", " ")
        if len(w) > 2 and w not in STOPWORDS and not w.isdigit():
            counts[w] += 1
    top = counts.most_common(TERMS_PER_EVENT)
    total = sum(n for _, n in top) or 1
    return {t: round(n / total, 4) for t, n in top}


# --------------------------------------------------------------------------- events
def record(kind: str, text: str = "", topics: Iterable[str] = (), source: str = "",
           cfg: MyGeekyConfig | None = None) -> None:
    """Remember that you engaged with something (terms only)."""
    if cfg is not None and not cfg.interest_learning:
        return
    terms = extract_terms(text, topics)
    if not terms or kind not in KIND_WEIGHTS:
        return
    ensure_dirs()
    event = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": kind,
             "source": source[:120], "terms": terms}
    with INTEREST_EVENTS_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")


def load_events() -> list[dict[str, Any]]:
    if not INTEREST_EVENTS_FILE.exists():
        return []
    out = []
    for line in INTEREST_EVENTS_FILE.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def learned_weights(cfg: MyGeekyConfig, now: datetime | None = None) -> dict[str, float]:
    """term -> weight, each event fading with the configured half-life."""
    if not cfg.interest_learning:
        return {}
    now = now or datetime.now(timezone.utc)
    weights: Counter[str] = Counter()
    for ev in load_events():
        try:
            age_days = (now - datetime.fromisoformat(ev["at"])).total_seconds() / 86400
        except (KeyError, ValueError, TypeError):
            continue
        fade = 0.5 ** (max(age_days, 0) / max(cfg.interest_half_life_days, 1))
        for term, share in (ev.get("terms") or {}).items():
            weights[term] += KIND_WEIGHTS.get(ev.get("kind"), 0.5) * float(share) * fade
    return dict(weights)


def learned_terms(cfg: MyGeekyConfig, n: int = 8) -> list[tuple[str, float]]:
    ranked = sorted(learned_weights(cfg).items(), key=lambda kv: kv[1], reverse=True)
    return [(t, round(w, 2)) for t, w in ranked if w >= MIN_LEARNED_WEIGHT][:n]


# --------------------------------------------------------------------------- your profile, offline
def profile_terms(cfg: MyGeekyConfig) -> dict[str, float]:
    """Your stated interests (topics, keywords, languages, CV, publications)
    plus what you've been engaging with lately -- built from local files only,
    so ranking never needs a network call. Weights are 0..1."""
    weights: dict[str, float] = {}
    for t in cfg.topics + cfg.keywords:
        weights[t.lower().replace("-", " ")] = 1.0
    for t in cfg.languages:
        weights[t.lower()] = 0.4
    corpus = ""
    if CV_TEXT_FILE.exists():
        corpus += CV_TEXT_FILE.read_text(encoding="utf-8", errors="ignore")
    try:
        from . import scholar
        corpus += " " + scholar.scholar_corpus(scholar.load_scholar_profile())
    except Exception:
        pass
    if corpus.strip():
        try:
            from .matcher import build_domain_vocabulary
            for term, w in build_domain_vocabulary(corpus, 60).items():
                if term.lower() not in STOPWORDS:
                    weights.setdefault(term.lower(), 0.8 * w)
        except Exception:
            pass
    learned = learned_terms(cfg, 15)
    if learned:
        top = learned[0][1]
        for term, w in learned:
            weights[term] = max(weights.get(term, 0.0), 0.3 + 0.7 * w / top)
    return weights


def _pattern(term: str) -> re.Pattern:
    words = [re.escape(w) for w in term.split()]
    return re.compile(r"\b" + r"[\s_-]+".join(words) + r"s?\b", re.I)


def match(text: str, weights: dict[str, float]) -> tuple[float, list[str]]:
    """(score 0..1, matched terms) of `text` against interest weights."""
    if not text or not weights:
        return 0.0, []
    hits = [(t, w) for t, w in weights.items() if len(t) >= 3 and t not in STOPWORDS and _pattern(t).search(text)]
    if not hits:
        return 0.0, []
    hits.sort(key=lambda kv: kv[1], reverse=True)
    score = 1 - math.prod(1 - min(w, 1.0) * 0.6 for _, w in hits[:5])   # diminishing returns
    return round(score, 4), [t for t, _ in hits[:4]]


# --------------------------------------------------------------------------- exploration
def explore_terms(cfg: MyGeekyConfig, k: int = 2, today: date | None = None) -> list[str]:
    """Today's 'new territory': fields you don't already follow, rotating daily."""
    known = set(profile_terms(cfg))
    pool = [t for t in EXPLORE_POOL if t not in known and not any(t in kt or kt in t for kt in known)]
    rnd = random.Random((today or date.today()).toordinal())
    rnd.shuffle(pool)
    return pool[:k]


def explore_count(n: int, cfg: MyGeekyConfig) -> int:
    return 0 if cfg.explore_share <= 0 or n <= 1 else max(1, round(n * cfg.explore_share))


def mix(ranked: list[dict[str, Any]], n: int, cfg: MyGeekyConfig,
        explore_pool: list[dict[str, Any]] | None = None, seed: int | None = None) -> list[dict[str, Any]]:
    """The best n - k items, then k from outside them (from `explore_pool`
    when given, else from further down the list), marked explore=True.
    Explore picks go last so your best matches always lead."""
    k = explore_count(n, cfg)
    head = [dict(x, explore=False) for x in ranked[: n - k]]
    taken = {id(x) for x in ranked[: n - k]}
    pool = [x for x in (explore_pool if explore_pool is not None else ranked[n - k:]) if id(x) not in taken]
    rnd = random.Random(seed if seed is not None else date.today().toordinal())
    picks = rnd.sample(pool, min(k, len(pool))) if pool else []
    return head + [dict(x, explore=True) for x in picks]


# --------------------------------------------------------------------------- learning from GitHub itself
def _load_seen() -> set[str]:
    from .config import INTEREST_SEEN_FILE
    try:
        return set(json.loads(INTEREST_SEEN_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def _save_seen(seen: set[str]) -> None:
    from .config import INTEREST_SEEN_FILE
    ensure_dirs()
    INTEREST_SEEN_FILE.write_text(json.dumps(sorted(seen)[-500:]), encoding="utf-8")


def learn_from_github(client, cfg: MyGeekyConfig, new_follows: Iterable[str] = (), max_lookups: int = 5) -> int:
    """New follows, and repos you starred or forked (from your own public
    events), become interest events. A few API calls at most; each star/fork
    is learned from once. Returns how many events were recorded."""
    if not cfg.interest_learning or not cfg.github_username:
        return 0
    recorded = 0
    for login in list(new_follows)[:max_lookups]:
        user = client.get_user(login) or {}
        text = " ".join(str(user.get(k) or "") for k in ("bio", "company", "name"))
        if text.strip():
            record("follow", text, source=f"followed {login}", cfg=cfg)
            recorded += 1
    seen = _load_seen()
    first_run = not seen
    lookups = 0
    for ev in client.list_user_events(cfg.github_username, per_page=30):
        kind = {"WatchEvent": "star", "ForkEvent": "fork"}.get(ev.get("type"))
        ev_id = str(ev.get("id") or "")
        if not kind or not ev_id or ev_id in seen:
            continue
        seen.add(ev_id)
        if first_run or lookups >= max_lookups:   # first run: just note what's there, don't flood
            continue
        name = (ev.get("repo") or {}).get("name", "")
        repo = client.get_repo(name) if name else None
        lookups += 1
        if repo:
            record(kind, f"{name.replace('/', ' ')} {repo.get('description') or ''} {repo.get('language') or ''}",
                   topics=repo.get("topics") or [], source=f"{kind} {name}", cfg=cfg)
            recorded += 1
    _save_seen(seen)
    return recorded
