"""Local persistence: suggestion history, training data, follow snapshots.

Everything here is plain JSON/JSONL under the user's data directory
(see config.py). None of it is a secret -- usernames, public counts, and
derived scores -- but none of it lives inside the project/repo either.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .config import (
    ACTIVITY_CACHE_FILE,
    CONTRIBUTE_LOG,
    EXCLUDED_FILE,
    FOLLOWING_SNAPSHOT,
    MODEL_HISTORY_LOG,
    SUGGESTIONS_LOG,
    TRAINING_LOG,
    ensure_dirs,
)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    ensure_dirs()
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def log_suggestions(records: Iterable[dict[str, Any]]) -> None:
    for r in records:
        append_jsonl(SUGGESTIONS_LOG, r)


def log_training_example(record: dict[str, Any]) -> None:
    append_jsonl(TRAINING_LOG, record)


def load_training_examples() -> list[dict[str, Any]]:
    return read_jsonl(TRAINING_LOG)


def load_following_snapshot() -> set[str]:
    if not FOLLOWING_SNAPSHOT.exists():
        return set()
    return set(json.loads(FOLLOWING_SNAPSHOT.read_text(encoding="utf-8")))


def save_following_snapshot(usernames: Iterable[str]) -> None:
    ensure_dirs()
    FOLLOWING_SNAPSHOT.write_text(json.dumps(sorted(set(usernames))), encoding="utf-8")


def load_excluded() -> set[str]:
    if not EXCLUDED_FILE.exists():
        return set()
    return set(json.loads(EXCLUDED_FILE.read_text(encoding="utf-8")))


def add_excluded(usernames: Iterable[str]) -> None:
    ensure_dirs()
    current = load_excluded()
    current.update(usernames)
    EXCLUDED_FILE.write_text(json.dumps(sorted(current)), encoding="utf-8")


def last_suggestions(limit: int = 15, list_type: str | None = None) -> list[dict[str, Any]]:
    records = read_jsonl(SUGGESTIONS_LOG)
    if list_type:
        records = [r for r in records if r.get("list") == list_type]
    return records[-limit:]


def log_model_history(record: dict[str, Any]) -> None:
    append_jsonl(MODEL_HISTORY_LOG, record)


def load_model_history(limit: int = 100) -> list[dict[str, Any]]:
    return read_jsonl(MODEL_HISTORY_LOG)[-limit:]


def load_activity_cache() -> dict[str, Any] | None:
    if not ACTIVITY_CACHE_FILE.exists():
        return None
    try:
        return json.loads(ACTIVITY_CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_activity_cache(events: list[dict[str, Any]], fetched_at: str,
                        following: Iterable[str] | None = None) -> None:
    ensure_dirs()
    payload: dict[str, Any] = {"fetched_at": fetched_at, "events": events}
    if following is not None:
        payload["following"] = sorted(following)
    ACTIVITY_CACHE_FILE.write_text(json.dumps(payload), encoding="utf-8")


def log_contributions(records: Iterable[dict[str, Any]]) -> None:
    for r in records:
        append_jsonl(CONTRIBUTE_LOG, r)


def last_contributions(limit: int = 10) -> list[dict[str, Any]]:
    """The most recent `mygeeky contribute` run's results, best first."""
    records = read_jsonl(CONTRIBUTE_LOG)
    if not records:
        return []
    latest = records[-1].get("timestamp")
    return [r for r in records if r.get("timestamp") == latest][:limit]
