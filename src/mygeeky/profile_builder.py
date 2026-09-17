"""Build a profile (interests + a text corpus for similarity scoring) for
either the user themself or a candidate, from their public GitHub repos."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .github_client import GitHubClient


@dataclass
class Profile:
    username: str
    bio: str = ""
    avatar_url: str = ""
    languages: Counter = field(default_factory=Counter)
    topics: Counter = field(default_factory=Counter)
    corpus: str = ""            # free-text blob used for TF-IDF similarity
    followers: int = 0
    following: int = 0
    public_repos: int = 0
    is_org: bool = False
    updated_at: str = ""        # most recently pushed-to repo's `pushed_at`


def _repo_facets(repos: list[dict[str, Any]]) -> tuple[Counter, Counter, list[str], str]:
    languages: Counter = Counter()
    topics: Counter = Counter()
    text_parts: list[str] = []
    latest_push = ""
    for repo in repos:
        if repo.get("fork"):
            continue
        lang = repo.get("language")
        if lang:
            languages[lang] += 1
        for topic in repo.get("topics") or []:
            topics[topic] += 1
        if repo.get("description"):
            text_parts.append(repo["description"])
        text_parts.append(repo.get("name", "").replace("-", " ").replace("_", " "))
        pushed = repo.get("pushed_at") or ""
        if pushed > latest_push:
            latest_push = pushed
    return languages, topics, text_parts, latest_push


def build_profile_from_github(client: GitHubClient, username: str, max_repo_pages: int = 3) -> Profile | None:
    user = client.get_user(username)
    if not user:
        return None
    repos = client.list_repos(username, max_pages=max_repo_pages)
    languages, topics, text_parts, latest_push = _repo_facets(repos)

    bio = user.get("bio") or ""
    corpus_bits = [bio, user.get("company") or "", user.get("login") or "", *text_parts]
    corpus_bits += list(languages.elements())
    corpus_bits += list(topics.elements())

    return Profile(
        username=user.get("login") or username,  # canonical casing from GitHub, not whatever casing we queried with
        bio=bio,
        avatar_url=user.get("avatar_url") or "",
        languages=languages,
        topics=topics,
        corpus=" \n ".join(b for b in corpus_bits if b),
        followers=user.get("followers", 0),
        following=user.get("following", 0),
        public_repos=user.get("public_repos", 0),
        is_org=(user.get("type") == "Organization"),
        updated_at=latest_push,
    )


def build_self_profile(client: GitHubClient, username: str, cv_text: str, keywords: list[str],
                        max_repo_pages: int = 5) -> Profile:
    profile = build_profile_from_github(client, username, max_repo_pages=max_repo_pages)
    if profile is None:
        profile = Profile(username=username)
    extra = " \n ".join([cv_text or "", " ".join(keywords)])
    profile.corpus = f"{profile.corpus}\n{extra}".strip()
    return profile
