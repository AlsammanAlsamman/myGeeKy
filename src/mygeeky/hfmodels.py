"""Hugging Face models on the Market: what's trending, in your field and everywhere.

Hugging Face's public API needs no key. Two reads, every few hours:

  * in your field: models tagged with your interests (`filter=<tag>`, sorted by
    Hugging Face's own trending score), e.g. biology, genomics, protein,
    medical -- tags work far better than name search, which mostly finds
    someone's first-attempt upload;
  * trending everywhere: the global top by trending score, the big picture.

Both are ranked with your model (interests.profile_terms), the same way as the
rest of myGeeKy. Only your interest tags are sent (as search filters).
Everything that comes back is someone else's text: ids are validated,
lengths capped, and links rebuilt from the id.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import requests

from . import interests
from .config import HF_MODELS_FILE, MyGeekyConfig, ensure_dirs

API = "https://huggingface.co/api/models"
UA = {"User-Agent": "mygeeky (https://github.com/AlsammanAlsamman/myGeeKy)"}
_ID_RE = re.compile(r"^[A-Za-z0-9][\w.-]{0,95}/[\w.-]{1,95}$")
_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9_:.+-]{0,59}$")
# Hugging Face tags for whole fields, reached from the words people use for them
FIELD_TAGS = {
    "biology": ("biology", "bioinformatics", "gene", "genome", "genomics", "genetics", "gwas", "protein",
                "rna", "dna", "cell", "single cell", "transcriptomics", "proteomics", "microbiome", "phylogenetics",
                "population genetics", "plant", "ecology", "evolution"),
    "genomics": ("genomics", "genome", "gwas", "genetics", "dna", "sequencing", "variant"),
    "protein": ("protein", "proteomics", "structure", "drug discovery", "antibody", "enzyme"),
    "medical": ("medical", "clinical", "disease", "health", "imaging", "radiology", "epidemiology", "drug"),
    "chemistry": ("chemistry", "molecule", "molecular", "cheminformatics", "materials"),
    "climate": ("climate", "weather", "earth", "remote sensing", "satellite"),
    "finance": ("finance", "economics", "trading"),
    "code": ("software", "programming", "code", "developer"),
    "math": ("math", "mathematics", "theorem", "statistics"),
}


def _int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def clean(m: Any) -> dict[str, Any] | None:
    if not isinstance(m, dict) or not isinstance(m.get("id"), str) or not _ID_RE.match(m["id"]):
        return None
    tags = [t for t in (m.get("tags") or []) if isinstance(t, str) and _TAG_RE.match(t)][:20]
    pipeline = m.get("pipeline_tag") if isinstance(m.get("pipeline_tag"), str) and _TAG_RE.match(m["pipeline_tag"]) else ""
    return {"id": m["id"], "likes": _int(m.get("likes")), "downloads": _int(m.get("downloads")),
            "trending": _int(m.get("trendingScore")), "pipeline": pipeline, "tags": tags,
            "created": str(m.get("createdAt") or "")[:10], "url": f"https://huggingface.co/{m['id']}"}


def _get(session: requests.Session, **params) -> list[dict[str, Any]]:
    r = session.get(API, params={"sort": "trendingScore", "limit": 40, **params}, headers=UA, timeout=25)
    r.raise_for_status()
    data = r.json()
    return [c for c in (clean(m) for m in (data if isinstance(data, list) else [])) if c]


def field_tags(weights: dict[str, float], extra: list[str], n: int = 5) -> list[str]:
    """The Hugging Face field tags your interests point to, strongest first."""
    scores: dict[str, float] = {}
    for term, w in weights.items():
        for tag, words in FIELD_TAGS.items():
            if term in words or any(term == word or (len(term) > 3 and term in word.split()) for word in words):
                scores[tag] = scores.get(tag, 0) + w
    for t in extra:                                  # your own keywords, as tags, count too
        slug = t.lower().strip().replace(" ", "-")
        if _TAG_RE.match(slug) and len(slug) >= 3:
            scores[slug] = scores.get(slug, 0) + 1.0
    return [t for t, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)][:n]


def _text(m: dict[str, Any]) -> str:
    return " ".join([m["id"].replace("/", " ").replace("-", " ").replace("_", " "), m["pipeline"].replace("-", " "),
                     " ".join(t.replace("-", " ") for t in m["tags"])])


def rank(models: list[dict[str, Any]], weights: dict[str, float]) -> list[dict[str, Any]]:
    out = []
    for m in models:
        relevance, matched = interests.match(_text(m), weights)
        out.append({**m, "match": matched,
                    "score": round((1 + relevance) * math.log1p(m["trending"] + m["likes"] / 20), 4)})
    return sorted(out, key=lambda m: m["score"], reverse=True)


def load_state() -> dict[str, Any]:
    try:
        return json.loads(HF_MODELS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict[str, Any]) -> None:
    ensure_dirs()
    HF_MODELS_FILE.write_text(json.dumps(state), encoding="utf-8")


def refresh_due(cfg: MyGeekyConfig, state: dict[str, Any], now: datetime | None = None) -> bool:
    try:
        age = (now or datetime.now(timezone.utc)) - datetime.fromisoformat(state["updated_at"])
    except (KeyError, ValueError, TypeError):
        return True
    return age >= timedelta(hours=cfg.market_hf_refresh_hours)


def refresh(cfg: MyGeekyConfig, force: bool = False, log: Callable[[str], None] = lambda m: None,
            session: requests.Session | None = None) -> dict[str, Any]:
    state = load_state()
    if not cfg.market_hf_enabled or (not force and not refresh_due(cfg, state)):
        return state
    session = session or requests.Session()
    weights = interests.profile_terms(cfg)
    tags = field_tags(weights, list(cfg.keywords) + list(cfg.topics))
    field: dict[str, dict[str, Any]] = {}
    errors = []
    for tag in tags:
        try:
            for m in _get(session, filter=tag, limit=30):
                if m["trending"] > 0 or m["likes"] >= 20:      # skip first-attempt uploads
                    field.setdefault(m["id"], {**m, "via": tag})
        except Exception as exc:
            errors.append(tag)
            log(f"hugging face: {tag} failed ({exc})")
    try:
        everywhere = _get(session, limit=60)
    except Exception as exc:
        errors.append("trending")
        log(f"hugging face: trending failed ({exc})")
        everywhere = []
    in_field = rank(list(field.values()), weights)[:cfg.market_hf_size]
    taken = {m["id"] for m in in_field}
    trending = [{**m, "match": []} for m in everywhere if m["id"] not in taken][:cfg.market_hf_size]
    new = {"updated_at": datetime.now(timezone.utc).isoformat(), "tags": tags,
           "field": in_field, "trending": trending, "errors": errors}
    if in_field or trending or not state:
        save_state(new)
        state = new
    log(f"hugging face: {len(in_field)} in your field ({', '.join(tags) or 'no field tags'}), "
        f"{len(trending)} trending")
    return state
