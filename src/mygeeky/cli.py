"""myGeeKy command-line interface.

myGeeKy finds fellow GitHub "geeks" who match your CV/repos and are likely
to follow back -- and only ever suggests them. It never calls a follow
endpoint; you always follow people yourself, by hand, on github.com.

Designed to be equally usable by a human in a terminal and by an AI agent
scripting against it: every command that produces results accepts `--json`
for machine-readable output.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import click

from . import __version__
from . import auth
from .config import (
    CV_TEXT_FILE,
    MyGeekyConfig,
    config_summary,
    load_config,
    save_config,
)
from .github_client import GitHubClient, build_search_queries
from .matcher import (
    LearnedModel,
    build_domain_vocabulary,
    compute_features,
    cross_validated_auc,
    domain_fit_score,
    final_score,
)
from .profile_builder import build_profile_from_github, build_self_profile
from .storage import (
    add_excluded,
    load_excluded,
    load_following_snapshot,
    load_training_examples,
    log_model_history,
    log_suggestions,
    log_training_example,
    save_following_snapshot,
)
from .text_utils import load_cv_text
from . import scholar


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _client_for(cfg: MyGeekyConfig) -> GitHubClient:
    token = auth.get_token(cfg.github_username)
    if token is None:
        click.echo(
            "No GitHub token found -- continuing unauthenticated (60 requests/hour, will be slow).\n"
            "Run `mygeeky auth login` for a much higher rate limit.",
            err=True,
        )
    return GitHubClient(token, rate_limit_sleep=cfg.rate_limit_sleep_seconds, search_pause=cfg.search_pause_seconds)


@click.group()
@click.version_option(__version__, prog_name="mygeeky")
def main() -> None:
    """myGeeKy - find fellow GitHub geeks who match you and are likely to follow back.

    myGeeKy only ever suggests people. It never follows anyone for you.
    """
    # On Windows, piped/redirected output (e.g. the scheduled weekly task's
    # log) falls back to cp1252, which can't encode the ★/→ used in output.
    import sys
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------- init
@main.command()
def init() -> None:
    """Interactive setup: your GitHub username, CV, and what you're looking for."""
    cfg = load_config()

    click.echo("Let's set myGeeKy up. Press Enter to accept any default shown in [brackets].\n")

    cfg.github_username = click.prompt("Your GitHub username", default=cfg.github_username or None)

    click.echo(
        "\nYour CV helps myGeeKy match you by skills/interests, not just repo languages."
    )
    cv_choice = click.prompt(
        "CV: (p)ath to a .txt/.md/.pdf file, (t)ype/paste text now, or (s)kip",
        type=click.Choice(["p", "t", "s"], case_sensitive=False),
        default="s",
    )
    if cv_choice.lower() == "p":
        cv_path = click.prompt("Path to your CV file", default=cfg.cv_path or None)
        text = _import_cv(cv_path)
        cfg.cv_path = cv_path
    elif cv_choice.lower() == "t":
        click.echo("Paste/type your CV text. Finish with a single line containing just: END")
        lines = []
        while True:
            line = input()
            if line.strip() == "END":
                break
            lines.append(line)
        text = "\n".join(lines)
        CV_TEXT_FILE.parent.mkdir(parents=True, exist_ok=True)
        CV_TEXT_FILE.write_text(text, encoding="utf-8")
        click.echo(f"Saved CV text ({len(text)} chars) to {CV_TEXT_FILE}")

    cv_orcid = scholar.find_orcid_in_text(_load_cv_text())
    click.echo("\nYour ORCID iD lets myGeeKy read your publications (ORCID + OpenAlex) to match\n"
               "you by research topic too. Blank to skip.")
    orcid = click.prompt("ORCID iD", default=cfg.orcid_id or cv_orcid or "", show_default=True)
    cfg.orcid_id = scholar.normalize_orcid(orcid)
    if orcid.strip() and not cfg.orcid_id:
        click.echo("That doesn't look like an ORCID iD -- skipped (set later with `mygeeky config set orcid_id ...`).")

    click.echo("\nYour Google Scholar profile adds your research interests and paper titles.\n"
               "Paste its URL (or just the user id). Blank to skip.")
    gs = click.prompt("Google Scholar profile", default=cfg.scholar_id or "", show_default=bool(cfg.scholar_id))
    cfg.scholar_id = scholar.normalize_scholar_id(gs)
    if gs.strip() and not cfg.scholar_id:
        click.echo("That doesn't look like a Scholar profile URL -- skipped "
                   "(set later with `mygeeky profile refresh --scholar URL`).")
    if cfg.orcid_id or cfg.scholar_id:
        _refresh_scholar(cfg)

    click.echo("\nWhat kind of geeks are you looking for? (comma-separated, blank to skip any)")
    langs = click.prompt("Programming languages", default=", ".join(cfg.languages) or "", show_default=False)
    topics = click.prompt("Topics/interests (e.g. bioinformatics, llm, game-dev)",
                           default=", ".join(cfg.topics) or "", show_default=False)
    keywords = click.prompt("Other keywords (free text, from your CV or interests)",
                             default=", ".join(cfg.keywords) or "", show_default=False)
    locations = click.prompt("Locations (optional, e.g. Cairo, Remote)",
                              default=", ".join(cfg.locations) or "", show_default=False)

    cfg.languages = [s.strip() for s in langs.split(",") if s.strip()]
    cfg.topics = [s.strip() for s in topics.split(",") if s.strip()]
    cfg.keywords = [s.strip() for s in keywords.split(",") if s.strip()]
    cfg.locations = [s.strip() for s in locations.split(",") if s.strip()]

    click.echo(
        "\nOptional extra candidate sources (beyond a plain GitHub search) -- these tend to\n"
        "surface much better matches: people who starred repos like yours, followers of a\n"
        "few well-known people in your field, etc. Blank to skip."
    )
    seed_accounts = click.prompt("Well-known GitHub accounts in your field (comma-separated usernames)",
                                  default=", ".join(cfg.seed_accounts) or "", show_default=False)
    seed_repos = click.prompt("Relevant repos, owner/name form (comma-separated)",
                               default=", ".join(cfg.seed_repos) or "", show_default=False)
    cfg.seed_accounts = [s.strip() for s in seed_accounts.split(",") if s.strip()]
    cfg.seed_repos = [s.strip() for s in seed_repos.split(",") if s.strip()]

    cfg.min_followers = click.prompt("Minimum followers", default=cfg.min_followers, type=int)
    cfg.max_followers = click.prompt("Maximum followers (avoid huge celebrity accounts)",
                                      default=cfg.max_followers, type=int)
    cfg.max_following = click.prompt(
        "Maximum accounts a candidate may be following (higher = allow more growth-hack-looking accounts)",
        default=cfg.max_following, type=int)
    cfg.min_public_repos = click.prompt("Minimum public repos", default=cfg.min_public_repos, type=int)
    cfg.max_suggestions_returned = click.prompt("Max suggestions per run", default=cfg.max_suggestions_returned, type=int)

    save_config(cfg)
    click.echo(f"\nSaved config to your myGeeKy config directory.\n{config_summary(cfg)}\n")

    if auth.get_token(cfg.github_username):
        click.echo("A GitHub token is already stored for this username.")
        if click.confirm("Replace it?", default=False):
            auth.prompt_and_store_token(cfg.github_username)
    else:
        if click.confirm("\nSet up your GitHub token now?", default=True):
            auth.prompt_and_store_token(cfg.github_username)

    if auth.get_token(cfg.github_username) and click.confirm(
        "\nBootstrap the learning model from accounts you already follow? "
        "(recommended -- gives myGeeKy real training data immediately instead of waiting\n"
        "weeks for new manual follows to accumulate; may take a few minutes)",
        default=True,
    ):
        ctx = click.get_current_context()
        ctx.invoke(bootstrap, limit=300)

    click.echo(
        "\nAll set. Try:\n"
        "  mygeeky run              # get suggestions now\n"
        "  mygeeky schedule show    # see how to run this automatically every week\n"
    )


def _import_cv(cv_path: str) -> str:
    text = load_cv_text(cv_path)
    CV_TEXT_FILE.parent.mkdir(parents=True, exist_ok=True)
    CV_TEXT_FILE.write_text(text, encoding="utf-8")
    click.echo(f"Saved CV text ({len(text)} chars) to {CV_TEXT_FILE}")
    return text


def _refresh_scholar(cfg: MyGeekyConfig) -> None:
    click.echo("Fetching your publications...")
    prof = scholar.refresh_scholar_profile(cfg.orcid_id, cfg.scholar_id)
    if cfg.orcid_id:
        oa = prof["openalex"]
        click.echo(f"  ORCID: {len(prof['orcid_record']['titles'])} works, "
                   f"{len(prof['orcid_record']['keywords'])} keywords")
        click.echo(f"  OpenAlex: {len(oa['works'])} works fetched, topics: {', '.join(oa['topics'][:5]) or '-'}")
    if cfg.scholar_id:
        gs = prof.get("google_scholar")
        if prof.get("google_scholar_blocked"):
            click.echo("  Google Scholar refused the request (it limits automated access) -- "
                       + ("kept the copy from last time." if gs else "try again later."))
        if gs:
            click.echo(f"  Google Scholar: {len(gs['titles'])} papers, "
                       f"interests: {', '.join(gs['interests']) or '-'}")


# --------------------------------------------------------------------------- profile
@main.group()
def profile() -> None:
    """Your profile sources: CV, ORCID/OpenAlex and Google Scholar publications."""


@profile.command("refresh")
@click.option("--cv", "cv_path", default=None, help="CV file (.pdf/.txt/.md); remembered for next time.")
@click.option("--orcid", default=None, help="ORCID iD or orcid.org URL; remembered for next time.")
@click.option("--scholar", "scholar_url", default=None,
              help="Google Scholar profile URL or user id; remembered for next time.")
def profile_refresh(cv_path: str | None, orcid: str | None, scholar_url: str | None) -> None:
    """Re-read your CV and re-fetch your publications. Run after updating your CV."""
    cfg = load_config()
    if cv_path:
        cfg.cv_path = cv_path
    if orcid is not None:
        cfg.orcid_id = scholar.normalize_orcid(orcid)
        if orcid and not cfg.orcid_id:
            raise click.ClickException(f"'{orcid}' is not a valid ORCID iD.")
    if scholar_url is not None:
        cfg.scholar_id = scholar.normalize_scholar_id(scholar_url)
        if scholar_url and not cfg.scholar_id:
            raise click.ClickException(f"'{scholar_url}' is not a Google Scholar profile URL or user id.")
    save_config(cfg)
    if cfg.cv_path:
        _import_cv(cfg.cv_path)
    else:
        click.echo("No CV path set (use --cv).")
    if cfg.orcid_id or cfg.scholar_id:
        _refresh_scholar(cfg)
    if not cfg.orcid_id:
        click.echo("No ORCID iD set (use --orcid).")
    if not cfg.scholar_id:
        click.echo("No Google Scholar profile set (use --scholar).")


@profile.command("show")
def profile_show() -> None:
    """Summarize what myGeeKy knows about you (no network calls)."""
    cfg = load_config()
    cv = _load_cv_text()
    sp = scholar.load_scholar_profile()
    click.echo(f"GitHub:   {cfg.github_username or '(not set)'}")
    click.echo(f"CV:       {cfg.cv_path or '(no path)'} -- {len(cv)} chars of text stored")
    click.echo(f"ORCID:    {cfg.orcid_id or '(not set)'}")
    click.echo(f"Scholar:  {cfg.scholar_id or '(not set)'}")
    if sp:
        oa = sp.get("openalex") or {}
        click.echo(f"Publications: {len(oa.get('works') or [])} from OpenAlex, "
                   f"{len((sp.get('orcid_record') or {}).get('titles') or [])} on ORCID, "
                   f"{len((sp.get('google_scholar') or {}).get('titles') or [])} on Google Scholar "
                   f"(fetched {sp.get('fetched_at', '?')[:10]})")
        click.echo(f"Research topics: {', '.join(scholar.scholar_topics(sp)) or '-'}")
    corpus = "\n".join([cv, scholar.scholar_corpus(sp), " ".join(cfg.keywords)])
    vocab = build_domain_vocabulary(corpus, cfg.domain_vocab_size)
    if vocab:
        top = sorted(vocab, key=vocab.get, reverse=True)
        click.echo(f"Top terms (CV + publications, before GitHub repos): {', '.join(top[:15])}")


# --------------------------------------------------------------------------- auth
@main.group()
def auth_cmd() -> None:
    """Manage your GitHub token (stored in the OS keyring, never in a file)."""


main.add_command(auth_cmd, name="auth")


@auth_cmd.command("login")
def auth_login() -> None:
    """Store a GitHub token securely in your OS keyring."""
    cfg = load_config()
    if not cfg.github_username:
        raise click.ClickException("Run `mygeeky init` first to set your GitHub username.")
    auth.prompt_and_store_token(cfg.github_username)


@auth_cmd.command("logout")
def auth_logout() -> None:
    """Remove the stored GitHub token."""
    cfg = load_config()
    if auth.delete_token(cfg.github_username):
        click.echo("Token removed from OS keyring.")
    else:
        click.echo("No token was stored.")


@auth_cmd.command("status")
def auth_status() -> None:
    """Show where (if anywhere) your token is coming from -- never prints the token itself."""
    cfg = load_config()
    click.echo(f"Token source: {auth.token_source(cfg.github_username)}")


# --------------------------------------------------------------------------- config
@main.group()
def config_cmd() -> None:
    """View or edit myGeeKy's parameters."""


main.add_command(config_cmd, name="config")


@config_cmd.command("show")
def config_show() -> None:
    cfg = load_config()
    click.echo(config_summary(cfg))


@config_cmd.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str) -> None:
    """Set a single config parameter, e.g. `mygeeky config set max_followers 3000`."""
    cfg = load_config()
    current = cfg.to_dict()
    if key not in current:
        raise click.ClickException(f"Unknown key '{key}'. Run `mygeeky config show` for valid keys.")
    old = current[key]
    if isinstance(old, bool):
        parsed: object = value.strip().lower() in ("1", "true", "yes", "y", "on")
    elif isinstance(old, int):
        parsed = int(value)
    elif isinstance(old, float):
        parsed = float(value)
    elif isinstance(old, list):
        parsed = [s.strip() for s in value.split(",") if s.strip()]
    else:
        parsed = value
    setattr(cfg, key, parsed)
    save_config(cfg)
    click.echo(f"{key} = {parsed}")


@config_cmd.command("reset")
def config_reset() -> None:
    if click.confirm("Reset all myGeeKy parameters to defaults?", default=False):
        save_config(MyGeekyConfig(github_username=load_config().github_username))
        click.echo("Config reset (username kept).")


# --------------------------------------------------------------------------- candidate collection
def _load_cv_text() -> str:
    if CV_TEXT_FILE.exists():
        return CV_TEXT_FILE.read_text(encoding="utf-8", errors="ignore")
    return ""


def _self_profile(client: GitHubClient, cfg: MyGeekyConfig):
    """You, as myGeeKy sees you: GitHub repos + CV text + ORCID/OpenAlex publications."""
    return build_self_profile(client, cfg.github_username, _load_cv_text(), cfg.keywords,
                              scholar_text=scholar.scholar_corpus(scholar.load_scholar_profile()))


def _domain_repo_queries(cfg: MyGeekyConfig, terms: list[str]) -> list[str]:
    since = (datetime.now(timezone.utc) - timedelta(days=cfg.contribute_pushed_within_days)).strftime("%Y-%m-%d")
    queries = []
    for term in terms:
        quoted = f'"{term}"' if " " in term else term
        queries.append(f"{quoted} in:name,description,topics fork:false archived:false "
                       f"stars:>=2 pushed:>{since}")
    return queries


def _gather_candidates(client: GitHubClient, cfg: MyGeekyConfig, exclude: set[str],
                        following: set[str], domain_terms: list[str] | None = None) -> dict[str, list[str]]:
    """Collect candidates from every configured source and tag each with
    where it came from. Returns {username: [source, ...]}, capped to
    `max_candidates_per_run` and prioritized by how many independent
    sources corroborate each candidate, then by whether any source is more
    targeted than the plain user search."""
    pool: dict[str, set[str]] = defaultdict(set)

    def add(login: str, source: str) -> None:
        if not login:
            return
        login_l = login.lower()
        if login_l in exclude:
            return
        pool[login_l].add(source)

    # 1. Plain GitHub user search (language/location/follower-range filters)
    queries = build_search_queries(cfg.languages, cfg.locations, cfg.min_followers,
                                    cfg.max_followers, cfg.min_public_repos)
    for q in queries:
        for item in client.search_users(q, max_pages=cfg.search_pages):
            add(item.get("login"), f"search:{q}")

    # 2. Followers of well-known accounts in your field
    for acct in cfg.seed_accounts:
        try:
            for login in client.list_followers(acct, max_pages=cfg.source_max_pages):
                add(login, f"follower_of:{acct}")
        except Exception as exc:
            click.echo(f"[mygeeky] seed_accounts '{acct}' failed: {exc}", err=True)

    # 3. Stargazers of relevant repos
    for repo in cfg.seed_repos:
        try:
            for login in client.list_stargazers(repo, max_pages=cfg.source_max_pages):
                add(login, f"stargazer:{repo}")
        except Exception as exc:
            click.echo(f"[mygeeky] seed_repos '{repo}' failed: {exc}", err=True)

    # 4. Stargazers of your own most-starred repos
    if cfg.include_own_stargazers:
        own_repos = client.list_repos(cfg.github_username, max_pages=2)
        top_repos = sorted(own_repos, key=lambda r: r.get("stargazers_count", 0), reverse=True)[:10]
        for r in top_repos:
            full = r.get("full_name")
            if not full:
                continue
            try:
                for login in client.list_stargazers(full, max_pages=cfg.source_max_pages):
                    add(login, f"starred_your_repo:{full}")
            except Exception:
                pass

    # 5. Second-degree: who a sample of your own followees follow (expensive; off by default)
    if cfg.include_second_degree and following:
        for acct in list(following)[: cfg.second_degree_sample]:
            try:
                for login in client.list_following(acct, max_pages=2):
                    add(login, f"second_degree_via:{acct}")
            except Exception:
                pass

    # 6. People behind active repos in your own field (owners + top contributors)
    if cfg.include_domain_repo_people and domain_terms:
        repos: dict[str, dict] = {}
        for q in _domain_repo_queries(cfg, domain_terms[: cfg.domain_repo_terms]):
            for r in client.search_repositories(q, max_pages=1, per_page=10):
                repos.setdefault(r.get("full_name") or "", r)
        repos.pop("", None)
        top = sorted(repos.values(), key=lambda r: r.get("stargazers_count", 0), reverse=True)
        for r in top[: cfg.domain_repo_count]:
            full = r["full_name"]
            owner = r.get("owner") or {}
            if owner.get("type") == "User":
                add(owner.get("login"), f"domain_repo_owner:{full}")
            try:
                for c in client.list_contributors(full, per_page=10):
                    if c.get("type") == "User":
                        add(c.get("login"), f"domain_repo_contributor:{full}")
            except Exception:
                pass

    def priority(kv: tuple[str, set[str]]) -> tuple[int, bool]:
        return len(kv[1]), any(not s.startswith("search:") for s in kv[1])

    ranked = sorted(pool.items(), key=priority, reverse=True)
    return {login: sorted(sources) for login, sources in ranked[: cfg.max_candidates_per_run]}


def _activity_ok(client: GitHubClient, username: str, cfg: MyGeekyConfig, cache: dict[str, bool]) -> bool:
    """Real per-repo activity check: does this account have a repo that's
    either freshly created or genuinely maintained (not a one-day
    dump-and-abandon)? Profile-level `updated_at` can reflect a bio edit
    with no real code behind it, so this is checked separately."""
    if username in cache:
        return cache[username]
    try:
        repos = client.list_repos(username, max_pages=1, per_page=10, sort="pushed")
    except Exception:
        cache[username] = False
        return False
    now = datetime.now(timezone.utc)
    ok = False
    for r in repos:
        if r.get("fork") or not r.get("pushed_at") or not r.get("created_at"):
            continue
        try:
            created = datetime.strptime(r["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            pushed = datetime.strptime(r["pushed_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        created_age, pushed_age = (now - created).days, (now - pushed).days
        recently_uploaded = created_age <= cfg.recent_upload_days
        regularly_maintained = (pushed_age <= cfg.max_repo_push_age_days
                                 and (created_age - pushed_age) >= cfg.min_maintain_span_days)
        if recently_uploaded or regularly_maintained:
            ok = True
            break
    cache[username] = ok
    return ok


def _apply_activity_qc(client: GitHubClient, cfg: MyGeekyConfig, ranked: list[dict],
                        limit: int, cache: dict[str, bool]) -> list[dict]:
    kept: list[dict] = []
    checked = 0
    for r in ranked:
        if len(kept) >= limit or checked >= cfg.activity_check_top_n:
            break
        checked += 1
        if _activity_ok(client, r["username"], cfg, cache):
            kept.append(r)
    return kept


def _plausible_followback(r: dict, cfg: MyGeekyConfig) -> bool:
    """Someone following 1 account against 10k followers won't notice you."""
    if r["followers"] > cfg.followback_max_followers:
        return False
    return r["following"] / max(r["followers"], 1) >= cfg.followback_min_ratio


def _run_suggestions(cfg: MyGeekyConfig) -> dict[str, list[dict]]:
    if not cfg.github_username:
        raise click.ClickException("Run `mygeeky init` first.")
    client = _client_for(cfg)

    self_profile = _self_profile(client, cfg)
    vocabulary = build_domain_vocabulary(self_profile.corpus, cfg.domain_vocab_size)

    following = set(client.list_following(cfg.github_username))
    save_following_snapshot(following)  # baseline for the next `learn` run, if none exists yet
    excluded = {u.lower() for u in load_excluded()} | {cfg.github_username.lower()} \
        | {u.lower() for u in cfg.exclude_users}
    if cfg.exclude_already_following:
        excluded |= {u.lower() for u in following}

    from .contribute import search_terms
    domain_terms = search_terms(cfg, self_profile, vocabulary,
                                keyword_counts=scholar.scholar_keyword_counts(scholar.load_scholar_profile()))
    candidates = _gather_candidates(client, cfg, excluded, following, domain_terms)
    model = LearnedModel.load()

    ts = _now()
    scored = []
    for username, sources in candidates.items():
        candidate = build_profile_from_github(client, username, max_repo_pages=1)
        if candidate is None:
            continue
        if candidate.is_org and cfg.exclude_organizations:
            continue
        if candidate.public_repos < cfg.min_public_repos:
            continue
        if candidate.following > cfg.max_following:
            continue
        if (cfg.require_followers_or_following and candidate.followers < cfg.min_followers_gate
                and candidate.following < cfg.min_following_gate):
            continue

        features = compute_features(self_profile, candidate)
        base_score, breakdown = final_score(features, cfg, model)
        source_boost = min(0.01 * (len(sources) - 1), 0.04) if len(sources) > 1 else 0.0
        domain_fit = domain_fit_score(candidate.corpus, vocabulary)

        scored.append({
            "username": candidate.username,
            "profile_url": f"https://github.com/{candidate.username}",
            "avatar_url": candidate.avatar_url,
            "score": round(base_score + source_boost, 4),
            "score_breakdown": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in breakdown.items()},
            "features": {k: round(v, 4) for k, v in features.as_dict().items()},
            "domain_fit": round(domain_fit, 4),
            "followers": candidate.followers,
            "following": candidate.following,
            "public_repos": candidate.public_repos,
            "bio": candidate.bio,
            "sources": sources[:4],
            "n_sources": len(sources),
            "timestamp": ts,
        })

    activity_cache: dict[str, bool] = {}

    followback_ranked = sorted((r for r in scored if r["score"] >= cfg.similarity_threshold
                                and _plausible_followback(r, cfg)),
                                key=lambda r: r["score"], reverse=True)
    followback_kept = _apply_activity_qc(client, cfg, followback_ranked, cfg.max_suggestions_returned, activity_cache)

    # Domain-fit highlights: ranked purely by match to your CV/repos, independent
    # of follow-back likelihood -- a niche domain expert who follows almost no
    # one on GitHub is exactly who the follow-back score would otherwise bury.
    domain_ranked = sorted((r for r in scored if r["domain_fit"] > 0),
                            key=lambda r: r["domain_fit"], reverse=True)
    domain_kept = _apply_activity_qc(client, cfg, domain_ranked, cfg.domain_highlight_count, activity_cache)

    # A candidate can legitimately qualify for both lists -- copy rather than
    # tag in place, otherwise the same dict (shared by reference between the
    # two filtered views) would have its "list" tag overwritten by whichever
    # loop ran second, corrupting the persisted log for both lists.
    followback_top = [dict(r, list="followback") for r in followback_kept]
    domain_top = [dict(r, list="domain") for r in domain_kept]
    log_suggestions(followback_top + domain_top)

    return {"followback": followback_top, "domain_highlights": domain_top}


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Print suggestions as JSON (for scripts/AI agents).")
def run(as_json: bool) -> None:
    """Search GitHub and print ranked suggestions. Never follows anyone."""
    cfg = load_config()
    results = _run_suggestions(cfg)
    _print_suggestions(results, as_json)


def _print_suggestions(results: dict[str, list[dict]], as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(results, indent=2))
        return
    followback = results.get("followback", [])
    highlights = results.get("domain_highlights", [])
    if not followback and not highlights:
        click.echo("No suggestions cleared the filters this time. Try loosening `similarity_threshold` "
                    "or `max_following`, or add some `seed_accounts`/`seed_repos`.")
        return
    if followback:
        click.echo(f"\n{len(followback)} suggested geeks, ranked by likely follow-back "
                    "(you follow them yourself -- myGeeKy never will):\n")
        for r in followback:
            click.echo(f"  {r['score']:.3f}  {r['username']:<25} {r['profile_url']}")
            if r["bio"]:
                click.echo(f"           {r['bio'][:90]}")
    if highlights:
        click.echo(f"\n{len(highlights)} domain-fit highlights "
                    "(best match to your CV/repos, regardless of follow-back likelihood):\n")
        for r in highlights:
            click.echo(f"  {r['domain_fit']:.3f}  {r['username']:<25} {r['profile_url']}")
            if r["bio"]:
                click.echo(f"           {r['bio'][:90]}")
    click.echo("\nReview a profile, and if they look like your kind of geek, follow them by hand.")


# --------------------------------------------------------------------------- suggestions (replay last run)
@main.command()
@click.option("--limit", default=15, show_default=True)
@click.option("--json", "as_json", is_flag=True)
def suggestions(limit: int, as_json: bool) -> None:
    """Show the suggestions from your last `mygeeky run`, without querying GitHub again."""
    from .storage import last_suggestions
    results = {
        "followback": last_suggestions(limit, list_type="followback"),
        "domain_highlights": last_suggestions(limit, list_type="domain"),
    }
    _print_suggestions(results, as_json)


# --------------------------------------------------------------------------- learning (shared by learn + bootstrap)
def _label_and_log(client: GitHubClient, cfg: MyGeekyConfig, self_profile, usernames,
                    recent_lookup: dict[str, dict] | None = None) -> tuple[int, int]:
    """For each username, check (read-only) whether they follow the user
    back and log a labeled training example. Returns (n_labeled, n_followed_back)."""
    recent_lookup = recent_lookup or {}
    n_labeled = 0
    n_followed_back = 0
    for username in usernames:
        record = recent_lookup.get(username)
        if record:
            features_vec = list(record["features"].values())
            following_count = record.get("following", 0)
        else:
            candidate = build_profile_from_github(client, username, max_repo_pages=1)
            if candidate is None or candidate.is_org:
                continue
            features_vec = compute_features(self_profile, candidate).as_vector()
            following_count = candidate.following

        label = 1 if client.is_following(username, cfg.github_username) else 0
        log_training_example({
            "username": username,
            "features": features_vec,
            "following": following_count,
            "label": label,
            "timestamp": _now(),
        })
        n_labeled += 1
        n_followed_back += label
        click.echo(f"  {username}: followed back = {bool(label)}")
    return n_labeled, n_followed_back


def _retrain_and_report(cfg: MyGeekyConfig) -> None:
    examples = load_training_examples()
    # accounts that mass-follow thousands of people are a growth-hacking
    # outlier, not a genuine reciprocity signal, and were distorting the
    # model when left in (mirrors what worked in real-world testing).
    filtered = [e for e in examples if e.get("following", 0) <= cfg.training_mass_follow_outlier]
    excluded_n = len(examples) - len(filtered)

    if len(filtered) < cfg.min_training_samples:
        click.echo(f"\n{len(filtered)}/{cfg.min_training_samples} labeled examples so far -- "
                   "using the heuristic scorer until there's enough to train on.")
        return

    X = [e["features"] for e in filtered]
    y = [e["label"] for e in filtered]
    model = LearnedModel()
    if not model.train(X, y):
        click.echo(f"\nHave {len(filtered)} examples but still need both follow-backs and "
                   "non-follow-backs to train.")
        return
    model.save()

    auc = cross_validated_auc(X, y)
    log_model_history({
        "timestamp": _now(),
        "n_train": len(filtered),
        "n_pos": int(sum(y)),
        "auc": auc,
    })
    auc_msg = f", cross-validated AUC {auc:.3f}" if auc is not None else ""
    excl_msg = f" (excluded {excluded_n} mass-follow outlier(s))" if excluded_n else ""
    click.echo(f"\nRetrained the model on {len(filtered)} labeled examples{auc_msg}{excl_msg}. "
               "Treat this as directional, not precise, especially with a small training set.")


# --------------------------------------------------------------------------- bootstrap
@main.command()
@click.option("--limit", default=300, show_default=True,
              help="Max accounts you already follow to check (each check is one API call).")
def bootstrap(limit: int) -> None:
    """Seed the learning model from accounts you ALREADY follow.

    Instead of waiting weeks for enough new manual follows to accumulate,
    this checks (read-only) whether each account you currently follow
    follows you back, and logs that as real, immediate training data.
    """
    cfg = load_config()
    if not cfg.github_username:
        raise click.ClickException("Run `mygeeky init` first.")
    client = _client_for(cfg)

    full_following = client.list_following(cfg.github_username)
    to_check = full_following[:limit] if limit else full_following
    if limit and len(full_following) > limit:
        click.echo(f"You follow {len(full_following)} accounts; checking the first {limit} "
                    "(raise with --limit for more).")

    self_profile = _self_profile(client, cfg)
    click.echo(f"Checking follow-back status for {len(to_check)} accounts you already follow...")
    n_labeled, n_back = _label_and_log(client, cfg, self_profile, to_check)

    save_following_snapshot(full_following)
    add_excluded(to_check)

    click.echo(f"\nLabeled {n_labeled} accounts -- {n_back} follow you back "
               f"({n_back / max(n_labeled, 1):.0%}).")
    _retrain_and_report(cfg)


# --------------------------------------------------------------------------- learn
@main.command()
def learn() -> None:
    """Check who you actually followed since the last run, learn from who followed back."""
    cfg = load_config()
    if not cfg.github_username:
        raise click.ClickException("Run `mygeeky init` first.")
    client = _client_for(cfg)

    previous = load_following_snapshot()
    current = set(client.list_following(cfg.github_username))

    if not previous:
        save_following_snapshot(current)
        click.echo("No previous snapshot found -- baseline established. Run `mygeeky learn` again next "
                    "week, or `mygeeky bootstrap` now to learn immediately from who you already follow.")
        return

    newly_followed = current - previous
    if not newly_followed:
        click.echo("You haven't followed anyone new since the last check -- nothing to learn from yet.")
        save_following_snapshot(current)
        return

    from .storage import last_suggestions
    recent = {r["username"]: r for r in last_suggestions(1000)}
    self_profile = _self_profile(client, cfg)

    n_labeled, n_back = _label_and_log(client, cfg, self_profile, newly_followed, recent)

    save_following_snapshot(current)
    add_excluded(newly_followed)
    _retrain_and_report(cfg)

    click.echo(f"\nLearned from {n_labeled} new follow(s) -- {n_back} followed back.")


# --------------------------------------------------------------------------- pipeline (for the weekly schedule)
@main.command()
def pipeline() -> None:
    """Sync pull, `learn`, `run`, `contribute`, sync push -- intended for the weekly scheduled task."""
    from . import sync as sync_mod
    cfg = load_config()
    syncing = bool(cfg.sync_repo and cfg.sync_auto and sync_mod.is_initialized())
    ctx = click.get_current_context()
    if syncing:
        try:
            msg = sync_mod.pull()
            click.echo(msg)
            if msg.startswith("Pulled"):
                _retrain_and_report(load_config())
        except sync_mod.SyncError as exc:
            click.echo(f"[mygeeky] sync pull failed, continuing with local data: {exc}", err=True)
    ctx.invoke(learn)
    click.echo("")
    ctx.invoke(run, as_json=False)
    click.echo("")
    ctx.invoke(contribute, as_json=False, last=False)
    if syncing:
        try:
            click.echo(sync_mod.push())
        except sync_mod.SyncError as exc:
            click.echo(f"[mygeeky] sync push failed (will retry next run): {exc}", err=True)


# --------------------------------------------------------------------------- contribute
def _run_contribute(cfg: MyGeekyConfig) -> list[dict]:
    from .contribute import suggest_repositories
    from .storage import log_contributions
    if not cfg.github_username:
        raise click.ClickException("Run `mygeeky init` first.")
    client = _client_for(cfg)
    self_profile = _self_profile(client, cfg)
    vocabulary = build_domain_vocabulary(self_profile.corpus, cfg.domain_vocab_size)
    results = suggest_repositories(client, cfg, self_profile, vocabulary,
                                   keyword_counts=scholar.scholar_keyword_counts(scholar.load_scholar_profile()),
                                   log=lambda m: click.echo(f"[mygeeky] {m}", err=True))
    log_contributions(results)
    return results


def _print_contributions(results: list[dict], as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(results, indent=2))
        return
    if not results:
        click.echo("No repos cleared the filters. Try `mygeeky config set contribute_extra_terms \"term1, term2\"` "
                   "or widen `contribute_pushed_within_days` / the star range.")
        return
    click.echo(f"\n{len(results)} repos you could improve (fork + PR them yourself -- myGeeKy never will):\n")
    for r in results:
        lang = f" [{r['language']}]" if r["language"] else ""
        click.echo(f"  {r['score']:.3f}  {r['full_name']}{lang}  \u2605{r['stars']}")
        if r["description"]:
            click.echo(f"         {r['description'][:100]}")
        if r["reasons"]:
            click.echo(f"         why: {'; '.join(r['reasons'])}")
        for issue in r["starter_issues"][:2]:
            click.echo(f"         \u2192 {issue['title'][:80]}  {issue['url']}")
        click.echo(f"         {r['repo_url']}")
    click.echo("\nPick an issue, fork the repo, and send a small focused PR.")


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Print results as JSON (for scripts/AI agents).")
@click.option("--last", is_flag=True, help="Re-print the last results without querying GitHub.")
def contribute(as_json: bool, last: bool) -> None:
    """Suggest repos matching your CV/repos/publications that you could fork,
    improve, and likely get merged. Never forks or opens PRs for you."""
    if last:
        from .storage import last_contributions
        _print_contributions(last_contributions(), as_json)
        return
    _print_contributions(_run_contribute(load_config()), as_json)


# --------------------------------------------------------------------------- sync
@main.group()
def sync() -> None:
    """Keep your myGeeKy data in a PRIVATE GitHub repo, to use it from any computer."""


def _sync_call(fn, *args) -> str:
    from . import sync as sync_mod
    try:
        return fn(*args)
    except sync_mod.SyncError as exc:
        raise click.ClickException(str(exc)) from exc


@sync.command("init")
@click.option("--repo", default=None, help="owner/name of the private repo [default: <you>/mygeeky-data].")
def sync_init(repo: str | None) -> None:
    """Create (if needed) the private repo and connect this machine to it."""
    from . import sync as sync_mod
    cfg = load_config()
    if not cfg.github_username and not repo:
        raise click.ClickException("Run `mygeeky init` first, or pass --repo owner/name.")
    repo = repo or f"{cfg.github_username}/mygeeky-data"
    click.echo(f"Syncing with PRIVATE repo {repo} -- it will hold your CV text and history.")
    click.echo(_sync_call(sync_mod.init, repo))
    cfg = load_config()  # may have just been replaced by the synced config
    cfg.sync_repo = repo
    save_config(cfg)
    _retrain_quietly()
    _sync_call(sync_mod.push)


def _retrain_quietly() -> None:
    from .config import MODEL_FILE
    if not MODEL_FILE.exists() and load_training_examples():
        _retrain_and_report(load_config())


@sync.command("push")
def sync_push() -> None:
    """Commit and push this machine's data."""
    from . import sync as sync_mod
    click.echo(_sync_call(sync_mod.push))


@sync.command("pull")
def sync_pull() -> None:
    """Fetch data from your other machines (then retrain the model locally)."""
    from . import sync as sync_mod
    msg = _sync_call(sync_mod.pull)
    click.echo(msg)
    if msg.startswith("Pulled"):
        _retrain_and_report(load_config())


@sync.command("status")
def sync_status() -> None:
    from . import sync as sync_mod
    click.echo(sync_mod.status())


# --------------------------------------------------------------------------- schedule
@main.group()
def schedule() -> None:
    """Set up (or remove) a weekly automatic run of myGeeKy."""


@schedule.command("show")
def schedule_show() -> None:
    from . import scheduler
    click.echo(scheduler.describe())


@schedule.command("install")
@click.option("--yes", is_flag=True, help="Actually register the weekly task/cron entry.")
def schedule_install(yes: bool) -> None:
    from . import scheduler
    click.echo(scheduler.install(confirmed=yes))


@schedule.command("remove")
def schedule_remove() -> None:
    from . import scheduler
    click.echo(scheduler.remove())


# --------------------------------------------------------------------------- gui
@main.command()
def gui() -> None:
    """Launch the live glass panel (requires `pip install "mygeeky[gui]"`)."""
    from .gui.app import main as gui_main
    gui_main()


if __name__ == "__main__":
    main()
