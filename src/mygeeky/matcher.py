"""Scoring and learning.

Cold start (no history yet): a transparent heuristic blend of
  - content similarity (TF-IDF cosine similarity between your CV/repo
    corpus and the candidate's bio/repo corpus)
  - a "likely to follow back" heuristic (people who follow a lot of others
    relative to their own follower count tend to reciprocate follows)
  - an activity/recency score (prefer active accounts over dormant ones)

Once `mygeeky learn` has collected enough labeled outcomes (did a person
you manually followed actually follow back, yes/no), a logistic-regression
classifier is trained on those examples and its prediction is blended into
the score too -- so future suggestions keep adapting to who actually
follows *you* back, not just the generic heuristic.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.preprocessing import StandardScaler

from .config import MODEL_FILE, MyGeekyConfig
from .profile_builder import Profile

FEATURE_NAMES = [
    "content_similarity",
    "follow_back_ratio",
    "activity_recency",
    "shared_languages",
    "shared_topics",
]


def _recency_score(iso_timestamp: str) -> float:
    if not iso_timestamp:
        return 0.0
    try:
        pushed = datetime.strptime(iso_timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return 0.0
    days = (datetime.now(timezone.utc) - pushed).days
    if days <= 30:
        return 1.0
    if days >= 720:
        return 0.0
    return max(0.0, 1.0 - (days - 30) / (720 - 30))


def _follow_back_ratio(followers: int, following: int) -> float:
    if followers <= 0 and following <= 0:
        return 0.0
    ratio = following / max(followers, 1)
    # People following roughly as many (or more) than follow them tend to
    # reciprocate; extreme celebrity accounts (huge followers, tiny
    # following) rarely follow back. Squash into 0..1.
    return min(1.0, ratio)


def content_similarity(self_corpus: str, candidate_corpus: str) -> float:
    if not self_corpus.strip() or not candidate_corpus.strip():
        return 0.0
    vectorizer = TfidfVectorizer(stop_words="english", max_features=2000)
    try:
        matrix = vectorizer.fit_transform([self_corpus, candidate_corpus])
    except ValueError:
        return 0.0
    sim = cosine_similarity(matrix[0:1], matrix[1:2])[0][0]
    return float(sim)


def shared_ratio(self_counter, candidate_counter) -> float:
    if not self_counter or not candidate_counter:
        return 0.0
    self_keys = set(self_counter.keys())
    cand_keys = set(candidate_counter.keys())
    if not self_keys:
        return 0.0
    overlap = self_keys & cand_keys
    return len(overlap) / len(self_keys)


@dataclass
class Features:
    content_similarity: float
    follow_back_ratio: float
    activity_recency: float
    shared_languages: float
    shared_topics: float

    def as_vector(self) -> list[float]:
        return [
            self.content_similarity,
            self.follow_back_ratio,
            self.activity_recency,
            self.shared_languages,
            self.shared_topics,
        ]

    def as_dict(self) -> dict[str, float]:
        return {
            "content_similarity": self.content_similarity,
            "follow_back_ratio": self.follow_back_ratio,
            "activity_recency": self.activity_recency,
            "shared_languages": self.shared_languages,
            "shared_topics": self.shared_topics,
        }


def compute_features(self_profile: Profile, candidate: Profile) -> Features:
    return Features(
        content_similarity=content_similarity(self_profile.corpus, candidate.corpus),
        follow_back_ratio=_follow_back_ratio(candidate.followers, candidate.following),
        activity_recency=_recency_score(candidate.updated_at),
        shared_languages=shared_ratio(self_profile.languages, candidate.languages),
        shared_topics=shared_ratio(self_profile.topics, candidate.topics),
    )


def heuristic_score(features: Features, cfg: MyGeekyConfig) -> float:
    return (
        cfg.content_similarity_weight * features.content_similarity
        + cfg.follow_back_ratio_weight * features.follow_back_ratio
        + cfg.activity_weight * features.activity_recency
    )


class LearnedModel:
    """Thin wrapper around a scikit-learn logistic regression, persisted to disk."""

    def __init__(self) -> None:
        self.pipeline: tuple[StandardScaler, LogisticRegression] | None = None

    @property
    def is_trained(self) -> bool:
        return self.pipeline is not None

    def train(self, X: list[list[float]], y: list[int]) -> bool:
        if len(set(y)) < 2:
            return False  # need both positive and negative examples
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        clf = LogisticRegression(max_iter=1000)
        clf.fit(X_scaled, y)
        self.pipeline = (scaler, clf)
        return True

    def predict_proba(self, features: Features) -> float | None:
        if self.pipeline is None:
            return None
        scaler, clf = self.pipeline
        X = scaler.transform([features.as_vector()])
        return float(clf.predict_proba(X)[0][1])

    def save(self, path: Path | None = None) -> None:
        # resolved at call time, not bound as a default at import time, so
        # tests (and any future runtime override) can point MODEL_FILE
        # elsewhere and actually have it take effect
        path = path or MODEL_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as fh:
            pickle.dump(self.pipeline, fh)

    @classmethod
    def load(cls, path: Path | None = None) -> "LearnedModel":
        path = path or MODEL_FILE
        model = cls()
        if path.exists():
            try:
                with path.open("rb") as fh:
                    model.pipeline = pickle.load(fh)
            except Exception:
                model.pipeline = None
        return model


def final_score(features: Features, cfg: MyGeekyConfig, model: LearnedModel) -> tuple[float, dict[str, Any]]:
    base = heuristic_score(features, cfg)
    ml_proba = model.predict_proba(features)
    if ml_proba is None:
        return base, {"heuristic": base, "ml_proba": None, "blended": base}
    blended = (1 - cfg.ml_blend_weight) * base + cfg.ml_blend_weight * ml_proba
    return blended, {"heuristic": base, "ml_proba": ml_proba, "blended": blended}


def build_domain_vocabulary(self_corpus: str, size: int = 25) -> dict[str, float]:
    """Derive a weighted domain vocabulary from the user's OWN CV/repo corpus
    (not a hardcoded field-specific wordlist -- it adapts to whoever runs
    this). Terms are 1-2 word phrases, weighted by how often they appear
    in the user's own material, normalized to 0..1 by the top term.

    This score is used to build a "domain fit" ranking that is deliberately
    independent of follow-back likelihood: a niche domain expert who
    follows almost no one on GitHub is exactly the kind of match the
    follow-back heuristic would otherwise bury.
    """
    if not self_corpus.strip():
        return {}
    vectorizer = CountVectorizer(stop_words="english", ngram_range=(1, 2), max_features=size, min_df=1)
    try:
        matrix = vectorizer.fit_transform([self_corpus])
    except ValueError:
        return {}
    counts = matrix.toarray()[0]
    terms = vectorizer.get_feature_names_out()
    if counts.max() == 0:
        return {}
    return {term: float(count) / float(counts.max()) for term, count in zip(terms, counts) if count > 0}


def domain_fit_score(candidate_text: str, vocabulary: dict[str, float]) -> float:
    if not vocabulary or not candidate_text.strip():
        return 0.0
    text = candidate_text.lower()
    matched = [weight for term, weight in vocabulary.items() if term in text]
    if not matched:
        return 0.0
    # cap by the sum of the top few weights so a handful of strong matches
    # already reaches ~1.0, rather than requiring the whole vocabulary to hit
    top_weights = sorted(vocabulary.values(), reverse=True)[:5]
    cap = sum(top_weights) or 1.0
    return min(sum(matched) / cap, 1.0)


def cross_validated_auc(X: list[list[float]], y: list[int]) -> float | None:
    """Report how well the learned model actually predicts follow-backs, so
    the user can see whether the model is trustworthy yet rather than take
    it on faith. Returns None when there isn't enough data to cross-validate."""
    y_arr = np.array(y)
    n_pos, n_neg = int(y_arr.sum()), int((1 - y_arr).sum())
    if n_pos < 2 or n_neg < 2:
        return None
    n_splits = max(2, min(5, n_pos, n_neg))
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    model = LogisticRegression(class_weight="balanced", max_iter=1000, C=0.5)
    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    try:
        proba_cv = cross_val_predict(model, X_scaled, y_arr, cv=cv, method="predict_proba")[:, 1]
        return float(roc_auc_score(y_arr, proba_cv))
    except ValueError:
        return None
