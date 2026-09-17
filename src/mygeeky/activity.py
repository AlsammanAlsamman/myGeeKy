"""Turn GitHub's public events feed into a friendly "what your friends are
up to" activity feed (pushes, merges, new repos, stars, releases, ...).

Read-only, like everything else in myGeeKy. One call to
`/users/{you}/received_events` covers everyone you follow at once -- the
same data source GitHub's own dashboard news feed uses -- rather than
polling every friend's own event stream individually.
"""

from __future__ import annotations

from typing import Any

from .github_client import GitHubClient


def _format_push(payload: dict[str, Any]) -> str:
    n = payload.get("size") or len(payload.get("commits", []) or [])
    return f"pushed {n} commit{'s' if n != 1 else ''}"


def _format_pull_request(payload: dict[str, Any]) -> str:
    action = payload.get("action", "updated")
    pr = payload.get("pull_request") or {}
    if action == "closed" and pr.get("merged"):
        return "merged a pull request"
    return f"{action} a pull request"


def _format_issue(payload: dict[str, Any]) -> str:
    return f"{payload.get('action', 'updated')} an issue"

def _format_create(payload: dict[str, Any]) -> str:
    ref_type = payload.get("ref_type")
    if ref_type == "repository":
        return "created a new repository"
    if ref_type == "branch":
        ref = payload.get("ref") or ""
        return f"created branch '{ref}'" if ref else "created a branch"
    return f"created a {ref_type or 'thing'}"


FORMATTERS = {
    "PushEvent": _format_push,
    "PullRequestEvent": _format_pull_request,
    "IssuesEvent": _format_issue,
    "CreateEvent": _format_create,
    "ReleaseEvent": lambda p: "published a release",
    "WatchEvent": lambda p: "starred the repo",
    "ForkEvent": lambda p: "forked the repo",
    "PublicEvent": lambda p: "open-sourced the repo",
    "IssueCommentEvent": lambda p: "commented on an issue",
    "PullRequestReviewEvent": lambda p: "reviewed a pull request",
    "PullRequestReviewCommentEvent": lambda p: "commented on a pull request",
}

# Rough icon hints for the GUI, keyed by event type (purely decorative).
ICONS = {
    "PushEvent": "push",
    "PullRequestEvent": "merge",
    "IssuesEvent": "issue",
    "CreateEvent": "new",
    "ReleaseEvent": "release",
    "WatchEvent": "star",
    "ForkEvent": "fork",
    "PublicEvent": "public",
    "IssueCommentEvent": "comment",
    "PullRequestReviewEvent": "review",
    "PullRequestReviewCommentEvent": "comment",
}


def format_event(event: dict[str, Any]) -> dict[str, Any] | None:
    etype = event.get("type")
    formatter = FORMATTERS.get(etype)
    if formatter is None:
        return None
    actor = event.get("actor") or {}
    repo = event.get("repo") or {}
    try:
        verb = formatter(event.get("payload") or {})
    except Exception:
        return None
    login = actor.get("login", "")
    repo_name = repo.get("name", "")
    return {
        "type": etype,
        "icon": ICONS.get(etype, "activity"),
        "actor": login,
        "actor_avatar": actor.get("avatar_url", ""),
        "profile_url": f"https://github.com/{login}" if login else "",
        "verb": verb,
        "repo": repo_name,
        "repo_url": f"https://github.com/{repo_name}" if repo_name else "",
        "created_at": event.get("created_at", ""),
    }


def get_recent_activity(client: GitHubClient, username: str, limit: int = 30) -> list[dict[str, Any]]:
    raw = client.list_received_events(username, per_page=min(max(limit * 2, 30), 100))
    formatted: list[dict[str, Any]] = []
    for event in raw:
        record = format_event(event)
        if record:
            formatted.append(record)
        if len(formatted) >= limit:
            break
    return formatted
