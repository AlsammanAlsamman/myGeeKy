"""What can a token actually do? -- so setup can tell token 1 from token 2.

myGeeKy uses two GitHub tokens with very different powers:

  token 1 (read)    reads public profiles, repos and followers. Must not be
                    able to follow anyone or change any repository.
  token 2 (beacon)  writes your Signals beacon, and should be able to write
                    nothing else.

GitHub doesn't list a fine-grained token's permissions, so we ask it with
probes that change nothing:

  * follow:  if you don't follow PROBE_ACCOUNTS[i], "unfollow" them. That's a
             no-op either way, but GitHub answers 204 only when the token
             holds Followers: write, and 403/404 when it doesn't. (Never sent
             when you do follow them -- we'd move to the next account.)
  * write:   create a git blob (a loose file object) in one of your repos.
             Nothing points at it, so it never shows up anywhere and GitHub
             garbage-collects it; GitHub answers 201 only with Contents: write.
  * classic tokens (ghp_/gho_) announce their scopes in X-OAuth-Scopes.

Tokens are never logged, stored or printed here.
"""

from __future__ import annotations

from typing import Any

import requests

API = "https://api.github.com"
PROBE_ACCOUNTS = ("octocat", "defunkt", "mojombo")
WRITE_SCOPES = {"repo", "public_repo"}
FOLLOW_SCOPES = {"user", "user:follow"}
BLOB = {"content": "myGeeKy permission check (unreferenced; safe to ignore)", "encoding": "utf-8"}


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def kind_of(token: str) -> str:
    if token.startswith("github_pat_"):
        return "fine-grained"
    if token.startswith("ghp_"):
        return "classic"
    if token.startswith("gho_"):
        return "OAuth"              # "Sign in with GitHub", or the GitHub CLI
    return "other"


def _can_follow(token: str, timeout: float) -> bool | None:
    for account in PROBE_ACCOUNTS:
        r = requests.get(f"{API}/user/following/{account}", headers=_h(token), timeout=timeout)
        if r.status_code in (401, 403):
            return False                  # can't even read who you follow, so can't follow
        if r.status_code == 204:
            continue                      # you follow them: never touch it, try the next one
        if r.status_code != 404:
            return None
        d = requests.delete(f"{API}/user/following/{account}", headers=_h(token), timeout=timeout)
        return d.status_code == 204
    return None


def _can_write(token: str, repo: str, timeout: float) -> bool | None:
    r = requests.post(f"{API}/repos/{repo}/git/blobs", headers=_h(token), json=BLOB, timeout=timeout)
    if r.status_code == 201:
        return True
    if r.status_code in (403, 404):
        return False
    return None                           # e.g. 409: the repo is still empty, so it can't tell


def _other_repo(user: str, timeout: float, skip: str) -> str | None:
    """One of your own non-empty public repos, other than `skip`, to test writes against."""
    r = requests.get(f"{API}/users/{user}/repos", params={"type": "owner", "sort": "pushed", "per_page": 30},
                     headers={"Accept": "application/vnd.github+json"}, timeout=timeout)
    if r.status_code != 200:
        return None
    for repo in r.json():
        if repo.get("size") and not repo.get("fork") and not repo.get("archived") \
                and repo.get("name", "").lower() != skip.lower():
            return repo["full_name"]
    return None


def capabilities(token: str, user: str, beacon_repo: str = "mygeeky-beacon",
                 timeout: float = 15.0) -> dict[str, Any]:
    """{"valid", "login", "kind", "scopes", "can_follow", "beacon_write", "other_repo", "other_write"}.
    True/False when GitHub said so, None when it couldn't be told."""
    token = token.strip()
    out: dict[str, Any] = {"valid": False, "kind": kind_of(token)}
    try:
        r = requests.get(f"{API}/user", headers=_h(token), timeout=timeout)
        if r.status_code != 200:
            return out
        out.update(valid=True, login=r.json().get("login", ""))
        scopes = r.headers.get("X-OAuth-Scopes")
        out["scopes"] = sorted(s.strip() for s in scopes.split(",") if s.strip()) if scopes is not None else None
        owner = user or out["login"]
        out["can_follow"] = _can_follow(token, timeout)
        out["beacon_write"] = _can_write(token, f"{owner}/{beacon_repo}", timeout)
        other = _other_repo(owner, timeout, skip=beacon_repo)
        out["other_repo"] = other
        out["other_write"] = _can_write(token, other, timeout) if other else None
    except requests.RequestException:
        out["unreachable"] = True
    if out.get("scopes") is not None:   # classic: the scopes are the truth
        s = set(out["scopes"])
        out["can_follow"] = out["can_follow"] or bool(s & FOLLOW_SCOPES)
        if s & WRITE_SCOPES:
            out["other_write"] = True if out.get("other_write") is None else out["other_write"]
    return out


def _same(a: str | None, b: str | None) -> bool:
    return bool(a and b and a.strip() == b.strip())


def judge(role: str, caps: dict[str, Any], user: str, other_token: str | None = None,
          token: str | None = None) -> dict[str, Any]:
    """role "read" (token 1) or "beacon" (token 2) -> {"ok", "errors", "warnings", "summary"}."""
    errors: list[str] = []
    warnings: list[str] = []
    if caps.get("unreachable"):
        return {"ok": False, "errors": ["Couldn't reach GitHub to check the token. Check your connection."],
                "warnings": [], "summary": ""}
    if not caps.get("valid"):
        return {"ok": False, "errors": ["GitHub didn't accept that token: it's mistyped, expired or revoked."],
                "warnings": [], "summary": ""}
    login = caps.get("login", "")
    if user and login.lower() != user.lower():
        errors.append(f"That token belongs to {login}, not {user}.")
    beacon = f"{user or login}/mygeeky-beacon"
    other = caps.get("other_repo") or "your other repos"

    if role == "read":
        if _same(token, other_token):
            errors.append("That's your Signals token (token 2). Token 1 is a separate, read-only token.")
        elif caps.get("other_write") or caps.get("beacon_write"):
            where = other if caps.get("other_write") else beacon
            errors.append(f"This token can change your repositories (it can write to {where}). Token 1 must "
                          "be read-only. If this is your Signals token, paste it on the Signals page; for token 1, "
                          "make a new token with Repository access: Public repositories, and nothing else set to "
                          "write.")
        if caps.get("can_follow"):
            errors.append("This token can follow and unfollow people. myGeeKy never does that, so its token "
                          "shouldn't be able to: set Followers to Read-only (classic tokens: untick user:follow).")
        if caps.get("can_follow") is None:
            warnings.append("Couldn't tell whether this token can follow people.")
    else:
        if _same(token, other_token):
            errors.append("That's the same token as token 1. Signals needs a second token, with write access "
                          "to mygeeky-beacon only.")
        if caps.get("beacon_write") is False:
            errors.append(f"This token can't write to {beacon}. Edit it on GitHub: Repository access → Only "
                          "select repositories → mygeeky-beacon, and Contents → Read and write.")
        if caps.get("other_write"):
            warnings.append(f"This token can also write to {other}. Signals only needs mygeeky-beacon: "
                            "limit it to that repo (Only select repositories) to be safe.")
        if caps.get("can_follow"):
            warnings.append("This token can also follow people, which Signals doesn't need: remove the "
                            "Followers permission.")
    kind = caps.get("kind", "")
    if kind in ("classic", "OAuth") and caps.get("scopes") and not errors:   # no scopes = public read-only
        warnings.append(f"This is a {kind} token, which can't be limited as tightly as a fine-grained one "
                        "(github_pat_…).")
    can = []
    can.append("writes to mygeeky-beacon" if caps.get("beacon_write") else
               "can't write to mygeeky-beacon" if caps.get("beacon_write") is False else "")
    can.append("writes to other repos" if caps.get("other_write") else
               "read-only elsewhere" if caps.get("other_write") is False else "")
    can.append("can follow" if caps.get("can_follow") else "can't follow" if caps.get("can_follow") is False else "")
    summary = f"{login} · {kind} · " + ", ".join(c for c in can if c)
    return {"ok": not errors, "errors": errors, "warnings": warnings, "summary": summary}


def check(role: str, token: str, user: str, other_token: str | None = None) -> dict[str, Any]:
    return judge(role, capabilities(token, user), user, other_token=other_token, token=token)
