"""Minimal, read-only GitHub REST API client.

Deliberate design constraint: this file contains no `follow` / `unfollow`
method, and never calls `PUT/DELETE /user/following/*`. myGeeKy suggests;
it does not act on GitHub on your behalf. If you ever extend this client,
keep it that way -- see README "Safety" section for why.
"""

from __future__ import annotations

import time
from typing import Any, Iterable, Iterator

import requests

API_ROOT = "https://api.github.com"


class GitHubClient:
    def __init__(self, token: str | None, rate_limit_sleep: float = 1.5, search_pause: float = 2.1,
                 user_agent: str = "mygeeky-cli"):
        self.session = requests.Session()
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": user_agent,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.session.headers.update(headers)
        self.rate_limit_sleep = rate_limit_sleep
        # GitHub's /search/* endpoints have their own, much tighter rate limit
        # (~30 requests/min) independent of the main 5000/hour REST limit, so
        # they need their own, longer pacing regardless of X-RateLimit-Remaining.
        self.search_pause = search_pause

    def _get(self, path: str, params: dict[str, Any] | None = None, is_search: bool = False) -> requests.Response:
        url = path if path.startswith("http") else f"{API_ROOT}{path}"
        resp = self.session.get(url, params=params, timeout=30)
        remaining = resp.headers.get("X-RateLimit-Remaining")
        if remaining is not None and int(remaining) <= 1:
            reset = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait = max(0, reset - int(time.time())) + 1
            print(f"[mygeeky] GitHub rate limit reached, waiting {wait}s...")
            time.sleep(wait)
        elif is_search and self.search_pause:
            time.sleep(self.search_pause)
        elif self.rate_limit_sleep:
            time.sleep(self.rate_limit_sleep)
        return resp

    def get_user(self, username: str) -> dict[str, Any] | None:
        resp = self._get(f"/users/{username}")
        if resp.status_code != 200:
            return None
        return resp.json()

    def get_authenticated_user(self) -> dict[str, Any]:
        resp = self._get("/user")
        resp.raise_for_status()
        return resp.json()

    def list_repos(self, username: str, max_pages: int = 3, per_page: int = 100,
                    sort: str = "updated") -> list[dict[str, Any]]:
        repos: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            resp = self._get(
                f"/users/{username}/repos",
                params={"per_page": per_page, "page": page, "sort": sort, "type": "owner"},
            )
            if resp.status_code != 200:
                break
            batch = resp.json()
            if not batch:
                break
            repos.extend(batch)
            if len(batch) < per_page:
                break
        return repos

    def _list_paginated_logins(self, path: str, max_pages: int = 10, per_page: int = 100) -> list[str]:
        logins: list[str] = []
        for page in range(1, max_pages + 1):
            resp = self._get(path, params={"per_page": per_page, "page": page})
            if resp.status_code != 200:
                break
            batch = resp.json()
            if not batch:
                break
            logins.extend(u["login"] for u in batch)
            if len(batch) < per_page:
                break
        return logins

    def list_followers(self, username: str, max_pages: int = 10) -> list[str]:
        return self._list_paginated_logins(f"/users/{username}/followers", max_pages=max_pages)

    def list_following(self, username: str, max_pages: int = 10) -> list[str]:
        return self._list_paginated_logins(f"/users/{username}/following", max_pages=max_pages)

    def list_stargazers(self, owner_repo: str, max_pages: int = 3) -> list[str]:
        """`owner_repo` is `"owner/name"`. Candidates who starred a relevant repo tend to
        be genuinely interested in the subject matter, not just search-matched."""
        return self._list_paginated_logins(f"/repos/{owner_repo}/stargazers", max_pages=max_pages)

    def list_received_events(self, username: str, per_page: int = 30) -> list[dict[str, Any]]:
        """Public activity from the accounts `username` follows (GitHub's own
        news-feed data source) -- one cheap call covers everyone you follow,
        rather than polling each friend's own event stream individually."""
        resp = self._get(f"/users/{username}/received_events", params={"per_page": per_page})
        if resp.status_code != 200:
            return []
        return resp.json()

    def is_following(self, source_username: str, target_username: str) -> bool:
        """True if `source_username` follows `target_username` (public, read-only check)."""
        resp = self._get(f"/users/{source_username}/following/{target_username}")
        return resp.status_code == 204

    def search_users(self, query: str, max_pages: int = 3, per_page: int = 30) -> Iterator[dict[str, Any]]:
        for page in range(1, max_pages + 1):
            resp = self._get(
                "/search/users",
                params={"q": query, "per_page": per_page, "page": page},
                is_search=True,
            )
            if resp.status_code != 200:
                break
            items = resp.json().get("items", [])
            if not items:
                break
            for item in items:
                yield item
            if len(items) < per_page:
                break


def build_search_queries(languages: Iterable[str], locations: Iterable[str],
                          min_followers: int, max_followers: int, min_repos: int) -> list[str]:
    """Build one or more GitHub user-search query strings from config facets.

    Fans out one query per language (or a single bare query if no languages
    are configured), each carrying the shared followers/repos/location
    filters. `topics` are not usable here (GitHub's /search/users endpoint
    has no `topic:` qualifier) -- they instead feed content-similarity
    scoring in matcher.py.
    """
    shared = [
        f"followers:{min_followers}..{max_followers}",
        f"repos:>={min_repos}",
        "type:user",
    ]
    for loc in locations:
        shared.append(f'location:"{loc}"')

    # Note: GitHub's /search/users endpoint has no `topic:` qualifier (that
    # only exists for /search/repositories), so `topics` is used later, in
    # matcher.py, for content-similarity scoring rather than the query itself.
    queries: list[str] = []
    langs = list(languages) or [None]
    for lang in langs:
        parts = list(shared)
        if lang:
            parts.append(f"language:{lang}")
        queries.append(" ".join(p for p in parts if p))
    return queries
