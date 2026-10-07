"""The keyword dictionary: keywords that mean something.

A keyword in the dictionary is a concept, not a string. "ai" holds machine
learning, deep learning, LLMs, pytorch... each with a weight, so choosing it
finds people, repos, papers and news about all of those. A keyword that isn't
in the dictionary still works, as a plain word (shown in red), and is sent to
myGeeKy's maker so the next dictionary can learn it:

  * automatically, if you're on Signals: your beacon's public interest tags
    already carry your keywords, and the maker's admin tab collects the ones
    the dictionary doesn't know (nothing extra is sent anywhere);
  * or when you click "suggest" on a red keyword: a prefilled GitHub issue
    you submit yourself (ideas.py).

The model is deliberately simple and explainable: topic co-occurrence on
GitHub. For each keyword (a GitHub topic) it reads the most-starred repos
carrying that topic and counts which other topics they carry:

    association(T -> U) = share of T's repos that also carry U
    specificity(U)      = how rare U is across everything read (so "python"
                          or "hacktoberfest" can't relate to everything)
    weight              = association x (0.35 + 0.65 x specificity)

It snowballs from a seed list (plus requested keywords) to the related topics
it finds. One GitHub search call per keyword; the maker runs it
(`mygeeky admin keywords build`) and publishes data/keywords.json. Everyone's
myGeeKy picks up a newer version by itself, at most once a week.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import requests

from .config import DATA_DIR, MyGeekyConfig, ensure_dirs

BUNDLED = Path(__file__).parent / "data" / "keywords.json"
CACHE_FILE = DATA_DIR / "keywords.json"
REMOTE_URL = "https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/src/mygeeky/data/keywords.json"
CHECK_EVERY_DAYS = 7
RELATED_WEIGHT = 0.6          # a related term counts at most this much of the keyword itself
MAX_RELATED = 12

# where the model starts; it then follows what these topics are used with
SEEDS = [
    "ai", "artificial-intelligence", "machine-learning", "deep-learning", "llm", "nlp", "computer-vision",
    "reinforcement-learning", "generative-ai", "data-science", "statistics", "bayesian", "causal-inference",
    "time-series", "visualization", "bioinformatics", "genomics", "genetics", "gwas", "single-cell",
    "rna-seq", "transcriptomics", "proteomics", "metagenomics", "microbiome", "phylogenetics",
    "population-genetics", "epidemiology", "neuroscience", "medical-imaging", "drug-discovery",
    "protein-structure", "cheminformatics", "plant-biology", "ecology", "climate", "remote-sensing",
    "gis", "physics", "astronomy", "chemistry", "materials-science", "quantum-computing", "robotics",
    "economics", "finance", "social-science", "education", "healthcare", "workflow", "snakemake",
    "nextflow", "hpc", "cloud", "kubernetes", "devops", "databases", "web-development", "rust",
    "python", "r", "julia", "cpp", "javascript", "security", "privacy", "open-science",
    "reproducibility", "research-software", "scientific-computing", "simulation", "optimization",
    "graph-neural-networks", "knowledge-graph", "recommender-system", "information-retrieval",
    "speech-recognition", "accessibility",
]
# what people type -> the topic GitHub uses
ALIASES = {
    "artificial intelligence": "artificial-intelligence", "a.i.": "ai", "ml": "machine-learning",
    "dl": "deep-learning", "large language models": "llm", "large-language-models": "llm", "llms": "llm",
    "natural language processing": "nlp", "cv": "computer-vision", "rl": "reinforcement-learning",
    "genai": "generative-ai", "scrna-seq": "single-cell", "scrnaseq": "single-cell", "single cell": "single-cell",
    "rnaseq": "rna-seq", "genome-wide association": "gwas", "c++": "cpp", "js": "javascript",
    "quantum": "quantum-computing", "gnn": "graph-neural-networks", "nf-core": "nextflow",
}
# topics that go with almost everything, so they say nothing about meaning
GENERIC = {
    "hacktoberfest", "awesome", "awesome-list", "list", "python", "python3", "javascript", "typescript",
    "java", "go", "golang", "r", "cpp", "c", "rust", "julia", "html", "css", "shell", "bash", "linux",
    "windows", "macos", "docker", "github", "open-source", "opensource", "free", "tutorial", "beginner",
    "good-first-issue", "first-timers-only", "api", "cli", "library", "framework", "app", "tool", "tools",
}
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,49}$")


def slug(term: str) -> str:
    """'Machine Learning' -> 'machine-learning' (GitHub's topic form)."""
    t = " ".join(str(term).strip().lower().split())
    t = ALIASES.get(t, t)
    t = re.sub(r"[^a-z0-9+#. -]", "", t).replace(" ", "-")
    return ALIASES.get(t, t.replace("+", "p").replace("#", "sharp").strip("-."))


def label_of(topic: str) -> str:
    return topic.replace("-", " ")


# --------------------------------------------------------------------------- using the dictionary
_loaded: dict[str, Any] | None = None


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("terms"), dict) else None


def load(force: bool = False) -> dict[str, Any]:
    """The newest dictionary we have: the one shipped with myGeeKy, or a newer
    one fetched since. {"version", "terms": {topic: {"label", "related": [[topic, w]...]}}}"""
    global _loaded
    if _loaded is not None and not force:
        return _loaded
    candidates = [d for d in (_read(BUNDLED), _read(CACHE_FILE)) if d]
    _loaded = max(candidates, key=lambda d: str(d.get("version", ""))) if candidates else {"version": "", "terms": {}}
    return _loaded


def lookup(term: str) -> dict[str, Any] | None:
    """The dictionary entry for what someone typed, or None if it's unknown."""
    terms = load()["terms"]
    s = slug(term)
    if s in terms:
        return {"topic": s, **terms[s]}
    if s.endswith("s") and s[:-1] in terms:          # "transformers" -> "transformer"
        return {"topic": s[:-1], **terms[s[:-1]]}
    return None


def known(term: str) -> bool:
    return lookup(term) is not None


def split_known(terms: Iterable[str]) -> tuple[list[str], list[str]]:
    """(green, red): keywords the dictionary knows, and the ones it doesn't."""
    green, red = [], []
    for t in terms:
        (green if known(t) else red).append(t)
    return green, red


def expand(terms: Iterable[str], base: float = 1.0) -> dict[str, float]:
    """{phrase: weight}: each known keyword with its related concepts (weighted
    by how strongly they go together), each unknown one as just itself."""
    out: dict[str, float] = {}
    for t in terms:
        entry = lookup(t)
        phrase = " ".join(str(t).lower().split())
        out[phrase] = max(out.get(phrase, 0.0), base)
        if not entry:
            continue
        out[label_of(entry["topic"])] = max(out.get(label_of(entry["topic"]), 0.0), base)
        for rel, w in entry.get("related", [])[:MAX_RELATED]:
            p = label_of(rel)
            if len(p) < 3:          # "r", "go": they'd match inside almost any text
                continue
            out[p] = max(out.get(p, 0.0), round(base * RELATED_WEIGHT * float(w), 4))
    return out


def enrich_vocabulary(vocabulary: dict[str, float], cfg: MyGeekyConfig) -> dict[str, float]:
    """Your domain vocabulary, plus what your keywords and topics mean. Terms
    you already have keep their own (higher) weight."""
    out = dict(vocabulary)
    for phrase, w in expand(list(cfg.keywords) + list(cfg.topics)).items():
        if len(phrase) >= 3:            # "ai" alone would match inside "said" or "main"
            out[phrase] = max(out.get(phrase, 0.0), w)
    return out


def refresh_if_due(now: datetime | None = None, timeout: float = 20.0) -> bool:
    """Fetch a newer published dictionary, at most once a week. True if it changed."""
    now = now or datetime.now(timezone.utc)
    cached = _read(CACHE_FILE) or {}
    try:
        checked = datetime.fromisoformat(cached.get("checked_at", ""))
        if (now - checked).days < CHECK_EVERY_DAYS:
            return False
    except ValueError:
        pass
    try:
        r = requests.get(REMOTE_URL, timeout=timeout)
        remote = r.json() if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        remote = None
    ensure_dirs()
    current = load(force=True)
    if isinstance(remote, dict) and isinstance(remote.get("terms"), dict) \
            and str(remote.get("version", "")) > str(current.get("version", "")):
        CACHE_FILE.write_text(json.dumps({**remote, "checked_at": now.isoformat()}), encoding="utf-8")
        load(force=True)
        return True
    CACHE_FILE.write_text(json.dumps({**(cached or current), "checked_at": now.isoformat()}), encoding="utf-8")
    return False


# --------------------------------------------------------------------------- red keywords, back to the maker
def requests_from_beacons(cache: dict[str, Any]) -> Counter:
    """Unknown keywords in everyone's public beacon interests: {word: how many people}."""
    from . import beacon
    counts: Counter = Counter()
    for login, entry in (cache.get("users") or {}).items():
        parsed = beacon.parse_beacon(entry.get("raw"), login, 90)
        if parsed:
            counts.update({t for t in parsed["interests"] if not known(t) and len(t) >= 2})
    return counts


def requests_from_issues(issues: list[dict[str, Any]]) -> Counter:
    """Unknown keywords people suggested with the "suggest" button."""
    counts: Counter = Counter()
    for i in issues:
        if i.get("kind") == "keyword":
            word = re.sub(r"^\W*keyword:\s*", "", i.get("title", ""), flags=re.I).strip().lower()
            if word and not known(word):
                counts[word] += 1
    return counts


def keyword_requests(client, cfg: MyGeekyConfig) -> list[dict[str, Any]]:
    """Red keywords from both routes, most-wanted first:
    [{"word", "people" (in beacons), "suggested" (issues)}]."""
    from . import beacon, ideas
    from_beacons = requests_from_beacons(beacon.refresh(client, cfg))
    from_issues = requests_from_issues(ideas.inbox(client, state="open", limit=100))
    words = set(from_beacons) | set(from_issues)
    rows = [{"word": w, "people": from_beacons.get(w, 0), "suggested": from_issues.get(w, 0)} for w in words]
    return sorted(rows, key=lambda r: (r["people"] + 2 * r["suggested"], r["word"]), reverse=True)


# --------------------------------------------------------------------------- the model (run by the maker)
def _repos_for(client, topic: str, per_page: int = 100) -> list[list[str]]:
    resp = client._get("/search/repositories", params={"q": f"topic:{topic} fork:false", "sort": "stars",
                                                       "order": "desc", "per_page": per_page}, is_search=True)
    if resp.status_code != 200:
        return []
    return [[t for t in (it.get("topics") or []) if _SLUG_RE.match(t)] for it in resp.json().get("items", [])]


def build(client, seeds: Iterable[str] = SEEDS, extra: Iterable[str] = (), max_terms: int = 300,
          min_repos: int = 15, log: Callable[[str], None] = lambda m: None) -> dict[str, Any]:
    """Learn the dictionary from GitHub (one search call per keyword)."""
    queue = list(dict.fromkeys([slug(s) for s in list(extra) + list(seeds) if _SLUG_RE.match(slug(s))]))
    seen: set[str] = set()
    per_topic: dict[str, list[list[str]]] = {}
    df: Counter = Counter()
    while queue and len(per_topic) < max_terms:
        topic = queue.pop(0)
        if topic in seen:
            continue
        seen.add(topic)
        repos = _repos_for(client, topic)
        if len(repos) < min_repos:
            continue
        per_topic[topic] = repos
        for topics in repos:
            df.update(set(topics))
        co = Counter(u for topics in repos for u in set(topics) if u != topic)
        queue += [u for u, _ in co.most_common(6) if u not in seen]
        if len(per_topic) % 25 == 0:
            log(f"learned {len(per_topic)} keywords")
    docs = sum(len(r) for r in per_topic.values()) or 1
    terms: dict[str, Any] = {}
    for topic, repos in per_topic.items():
        n = len(repos)
        co = Counter(u for topics in repos for u in set(topics) if u != topic)
        scored = []
        for u, c in co.items():
            if c < 3 or u in GENERIC or len(u) < 2:
                continue
            specificity = math.log(docs / df[u]) / math.log(docs) if df[u] else 0.0
            scored.append((u, (c / n) * (0.35 + 0.65 * max(specificity, 0.0))))
        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[0][1] if scored else 1.0
        terms[topic] = {"label": label_of(topic), "repos": n,
                        "related": [[u, round(s / top, 3)] for u, s in scored[:MAX_RELATED]]}
    return {"version": datetime.now(timezone.utc).strftime("%Y.%m.%d.%H%M"),
            "built_from": f"GitHub topics of the most-starred repos, {len(terms)} keywords, {docs} repo listings",
            "terms": terms}


def save(dictionary: dict[str, Any], path: Path = BUNDLED) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dictionary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    load(force=True)
    return path
