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
from pathlib import Path

import click

from . import __version__
from . import auth
from . import keywords
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
    from . import use_system_certificates
    use_system_certificates()
    # On Windows, piped/redirected output (e.g. the scheduled weekly task's
    # log) falls back to cp1252, which can't encode the ★/→ used in output.
    import sys
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    _maybe_announce_update()


def _maybe_announce_update() -> None:
    """One line on stderr when a newer myGeeKy is out -- only for a person at a
    terminal (never in scripts, --json, the weekly job, or `update` itself), and
    the PyPI check runs at most once a day."""
    import sys
    argv = sys.argv[1:]
    if (not (sys.stdout and sys.stdout.isatty()) or "--json" in argv or not argv
            or argv[0] in ("update", "pipeline", "gui", "setup")):
        return
    try:
        if not load_config().check_for_updates:
            return
        from . import updates
        info = updates.check(timeout=2.0)
    except Exception:
        return
    if info["newer"]:
        click.secho(f"myGeeKy {info['latest']} is available (you have {info['current']}). "
                    "Run `mygeeky update` to get it.\n", fg="magenta", err=True)
    try:
        from . import tokens
        for t in tokens.warnings(load_config()):
            click.secho(t["message"] + "\n", fg="yellow", err=True)
    except Exception:
        pass   # a reminder must never break the command it's attached to


# --------------------------------------------------------------------------- update
@main.command()
@click.option("--check", "only_check", is_flag=True, help="Only say whether there's a newer version.")
def update(only_check: bool) -> None:
    """Update myGeeKy to the latest version (pip, for this same Python)."""
    from . import updates
    info = updates.check(force=True)
    if not info["latest"]:
        raise click.ClickException("Couldn't reach PyPI to check for a new version. Try again later.")
    if not info["newer"]:
        click.echo(f"You have the latest myGeeKy ({info['current']}).")
        return
    click.echo(f"myGeeKy {info['latest']} is available (you have {info['current']}).\n"
               f"What's new: {updates.RELEASES_URL}")
    if only_check:
        return
    click.echo("Updating...")
    ok, message = updates.run_upgrade()
    if not ok:
        raise click.ClickException(message)
    click.secho(message, fg="green")
    click.echo("If the panel is open, it picks up the new version the next time it starts "
               "(or click Update in the panel).")


def entry() -> None:
    """The `mygeeky` command: main(), but an unexpected failure gets a clear
    sentence and a saved report instead of a raw traceback."""
    try:
        main(prog_name="mygeeky")
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:   # click already handled its own errors and SystemExit
        from .config import LOG_DIR
        from .errors import ISSUES_URL, describe, save_crash_report
        report = save_crash_report(exc, LOG_DIR, "command line")
        click.secho(f"myGeeKy hit a problem: {describe(exc)}", fg="red", err=True)
        if report:
            click.echo(f"Full details were saved to {report}", err=True)
        click.echo(f"If it keeps happening, please open an issue at {ISSUES_URL} and attach that file.",
                   err=True)
        raise SystemExit(1)


# --------------------------------------------------------------------------- setup / uninstall windows
@main.command("setup")
def setup_window() -> None:
    """Open the setup window (the same as the Windows installer's), to set up or change myGeeKy."""
    from .gui.setup_wizard import main as setup_main
    raise SystemExit(setup_main([]))


@main.command("uninstall")
def uninstall_window() -> None:
    """Open the step-by-step uninstall window."""
    from .gui.uninstall_wizard import main as uninstall_main
    raise SystemExit(uninstall_main())


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
            _connect_github(cfg)
    else:
        _connect_github(cfg)

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


def _github_sign_in(cfg) -> bool:
    """Sign in with GitHub (the device flow): True when it worked."""
    from . import github_login as gl
    try:
        flow = gl.start()
        click.echo(f"\n  1. Open {flow['verification_uri']}  (your browser should open it now)")
        click.secho(f"  2. Enter this code:  {flow['user_code']}", bold=True)
        click.echo("  3. Click Authorize myGeeKy. It can only read public data.\n")
        click.launch(flow["verification_uri"])
        click.echo("Waiting for you on github.com…")
        token = gl.poll(flow["device_code"], flow["interval"], flow["expires_in"])
        login = gl.who(token)
    except gl.LoginError as exc:
        click.secho(str(exc), fg="red")
        return False
    if cfg.github_username and login.lower() != cfg.github_username.lower():
        click.secho(f"You signed in as {login}, but myGeeKy is set up for {cfg.github_username}. "
                    "Sign in with that account.", fg="red")
        return False
    if not cfg.github_username:
        cfg.github_username = login
        save_config(cfg)
    gl.store(token, login)
    click.secho(f"Signed in as {login}.", fg="green")
    return True


def _connect_github(cfg) -> None:
    """Connect GitHub during init: signing in is the easy way; pasting a token you
    made yourself is the other; either can be done later."""
    click.echo("\nConnect your GitHub account (read-only: myGeeKy can never follow, star or post):")
    click.echo("  (s) Sign in with GitHub    easiest: type a short code on GitHub's page, no token to make")
    click.echo("  (p) Paste a token          one you created yourself")
    click.echo("  (k) Skip for now           later: `mygeeky auth login`")
    choice = click.prompt("Choose", type=click.Choice(["s", "p", "k"], case_sensitive=False), default="s")
    if choice.lower() == "s":
        if not _github_sign_in(cfg) and click.confirm("Paste a token instead?", default=False):
            choice = "p"
    if choice.lower() == "p":
        for attempt in range(3):
            try:
                auth.prompt_and_store_token(cfg.github_username, show_guide=attempt == 0)
                return
            except ValueError as exc:
                click.secho(str(exc), fg="red")
                if attempt < 2 and not click.confirm("Try again?", default=True):
                    break
        click.echo("No token saved. Do it any time with `mygeeky auth login`.")


@auth_cmd.command("login")
@click.option("--paste", is_flag=True, help="Paste a token you made yourself instead of signing in.")
def auth_login(paste: bool) -> None:
    """Sign in with GitHub (no token to create or copy)."""
    cfg = load_config()
    if paste:
        if not cfg.github_username:
            raise click.ClickException("Run `mygeeky init` first to set your GitHub username.")
        auth.prompt_and_store_token(cfg.github_username)
    elif not _github_sign_in(cfg):
        raise click.ClickException("Not signed in. Try again, or `mygeeky auth login --paste` to paste a token.")
    from . import tokens
    tokens.forget()
    for t in tokens.status(cfg, force=True):
        if t["name"] == "read":
            click.echo(t["message"])


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
    from . import tokens
    cfg = load_config()
    from . import token_check
    user = cfg.github_username
    click.echo(f"Token source: {auth.token_source(user)}")
    for t in tokens.status(cfg, force=True):
        click.secho(f"  {'!' if t['warn'] else '-'} {t['message']}", fg="yellow" if t["warn"] else None)
    t1, t2 = auth.get_token(user), auth.get_beacon_token(user)
    for role, label, token, other in (("read", "Token 1 (read-only)", t1, t2), ("beacon", "Token 2 (Signals)", t2, t1)):
        if not token:
            continue
        v = token_check.check(role, token, user, other_token=other)
        click.secho(f"  {'✓' if v['ok'] else '✗'} {label}: {v['summary']}", fg=None if v["ok"] else "red")
        for msg in v["errors"]:
            click.secho(f"      ✗ {msg}", fg="red")
        for msg in v["warnings"]:
            click.secho(f"      ! {msg}", fg="yellow")
    click.echo(f"Product Hunt token: {'set' if auth.get_producthunt_token(cfg.github_username) else 'not set'}")
    click.echo(f"Renew tokens at {tokens.SETTINGS_URL} (open a token, then 'Regenerate token').")


@auth_cmd.command("producthunt")
@click.option("--remove", is_flag=True, help="Forget the stored Product Hunt token.")
def auth_producthunt(remove: bool) -> None:
    """Store a Product Hunt developer token, for launches in your field on the Market tab."""
    cfg = load_config()
    if not cfg.github_username:
        raise click.ClickException("Run `mygeeky init` first.")
    if remove:
        import keyring
        try:
            keyring.delete_password(auth.PRODUCTHUNT_SERVICE_NAME, cfg.github_username)
            click.echo("Product Hunt token removed.")
        except Exception:
            click.echo("No Product Hunt token was stored.")
        return
    auth.prompt_and_store_producthunt_token(cfg.github_username)
    click.echo("Run `mygeeky market --refresh` (or click Refresh on the Market tab) to load launches.")


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
                        following: set[str], domain_terms: list[str] | None = None,
                        beacon_signals: dict[str, str] | None = None) -> dict[str, list[str]]:
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

    # 7. myGeeKy users: people who signalled you, and beacons sharing your interests
    for login, source in (beacon_signals or {}).items():
        add(login, f"beacon:{source}")

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
    vocabulary = keywords.enrich_vocabulary(build_domain_vocabulary(self_profile.corpus, cfg.domain_vocab_size), cfg)

    following = set(client.list_following(cfg.github_username))
    save_following_snapshot(following)  # baseline for the next `learn` run, if none exists yet
    excluded = {u.lower() for u in load_excluded()} | {cfg.github_username.lower()} \
        | {u.lower() for u in cfg.exclude_users}
    if cfg.exclude_already_following:
        excluded |= {u.lower() for u in following}

    from .contribute import search_terms
    domain_terms = search_terms(cfg, self_profile, vocabulary,
                                keyword_counts=scholar.scholar_keyword_counts(scholar.load_scholar_profile()))
    beacon_signals: dict[str, str] = {}
    if cfg.beacon_enabled:
        from . import beacon as bc
        try:
            beacon_signals = bc.suggestion_signals(bc.refresh(client, cfg), cfg, bc.private_key_or_none(cfg))
        except Exception as exc:  # a beacon hiccup must never sink the whole search
            click.echo(f"[mygeeky] reading beacons failed, skipping them: {exc}", err=True)
    candidates = _gather_candidates(client, cfg, excluded, following, domain_terms, beacon_signals)
    model = LearnedModel.load()
    from . import interests
    interest_weights = interests.profile_terms(cfg)

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
        # someone who signalled you has already shown interest -- the strongest follow-back hint there is
        source_boost += {"signalled_you": 0.08, "mygeeky_user": 0.02}.get(beacon_signals.get(username, ""), 0.0)
        domain_fit = domain_fit_score(candidate.corpus, vocabulary)
        # people working on what you've been engaging with lately rank a little higher
        interest_boost, interest_terms = interests.match(candidate.corpus, interest_weights)
        base_score += 0.1 * interest_boost

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
    # keep some places for people outside your usual circle ("new territory");
    # the domain-fit list below stays a pure match to your field
    explored = interests.mix(followback_ranked, cfg.max_suggestions_returned, cfg)
    chosen = {r["username"] for r in explored}
    followback_ranked = explored + [dict(r, explore=False) for r in followback_ranked if r["username"] not in chosen]
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
    try:   # who you chose to follow says what you're into lately
        from . import interests
        interests.learn_from_github(client, cfg, newly_followed)
    except Exception as exc:
        click.echo(f"[mygeeky] couldn't learn interests from new follows: {exc}", err=True)

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
    vocabulary = keywords.enrich_vocabulary(build_domain_vocabulary(self_profile.corpus, cfg.domain_vocab_size), cfg)
    results = suggest_repositories(client, cfg, self_profile, vocabulary,
                                   keyword_counts=scholar.scholar_keyword_counts(scholar.load_scholar_profile()),
                                   log=lambda m: click.echo(f"[mygeeky] {m}", err=True))
    _annotate_papers(client, results, "full_name")
    log_contributions(results)
    return results


def _annotate_papers(client: GitHubClient, rows: list[dict], key: str) -> None:
    """The green [P]: attach each repo's published paper, if it has one."""
    from . import papers
    try:
        found = papers.annotate_repos(client, [r[key] for r in rows if r.get(key)])
    except Exception as exc:   # a paper lookup must never sink the list itself
        click.echo(f"[mygeeky] paper lookup skipped: {exc}", err=True)
        return
    for r in rows:
        if r.get(key) in found:
            r["paper"] = found[r[key]]


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


# --------------------------------------------------------------------------- market
def _market_terms(client: GitHubClient, cfg: MyGeekyConfig) -> list[str]:
    from .contribute import search_terms
    self_profile = _self_profile(client, cfg)
    vocabulary = keywords.enrich_vocabulary(build_domain_vocabulary(self_profile.corpus, cfg.domain_vocab_size), cfg)
    return search_terms(cfg, self_profile, vocabulary,
                        keyword_counts=scholar.scholar_keyword_counts(scholar.load_scholar_profile()))


def _run_market(cfg: MyGeekyConfig, force: bool = False, log=lambda m: None) -> list[dict]:
    from .market import compute_board, refresh_market
    if not cfg.github_username:
        raise click.ClickException("Run `mygeeky init` first.")
    client = _client_for(cfg)
    state = refresh_market(client, cfg, lambda: _market_terms(client, cfg), force=force, log=log)
    _refresh_producthunt(cfg, client, force=force, log=log)
    board = compute_board(state)
    _annotate_papers(client, board, "repo")
    return board


def _refresh_producthunt(cfg: MyGeekyConfig, client: GitHubClient, force: bool = False,
                         log=lambda m: None) -> None:
    """Product Hunt launches in your field (the API with a token, the public feed
    without), and Hugging Face models; a failure here never sinks the board itself."""
    from . import hfmodels, producthunt
    token = auth.get_producthunt_token(cfg.github_username)
    try:
        hfmodels.refresh(cfg, force=force, log=log)
    except Exception as exc:
        log(f"Hugging Face skipped: {exc}")
    try:
        producthunt.refresh(cfg, token, lambda: _market_terms(client, cfg), force=force, log=log)
    except Exception as exc:
        log(f"Product Hunt skipped: {exc}")


def _fmt_count(n: float) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else f"{n:.0f}"


@main.command()
@click.option("--refresh", is_flag=True, help="Take a new snapshot now, even if today's exists.")
@click.option("--last", is_flag=True, help="Show the saved board without querying GitHub/PyPI.")
@click.option("--json", "as_json", is_flag=True, help="Print the board as JSON.")
def market(refresh: bool, last: bool, as_json: bool) -> None:
    """A momentum board ("stock race") of the popular, active repos in your
    field: stars gained, commits, PyPI downloads and their trend."""
    from .market import compute_board, load_state
    cfg = load_config()
    rows = compute_board(load_state()) if last else         _run_market(cfg, force=refresh, log=lambda m: click.echo(f"[mygeeky] {m}", err=True))
    if as_json:
        click.echo(json.dumps(rows, indent=2))
        return
    if not rows:
        click.echo("The board is empty -- run `mygeeky market` (without --last), or add repos with "
                   "`mygeeky config set market_pinned \"owner/repo, owner/repo\"`.")
        return
    for r in rows:
        move = r["movement"]
        move_txt = "NEW" if move == "new" else "  -" if not move else f"{'+' if move > 0 else ''}{move}"
        stars_week = "collecting" if r["stars_week"] is None else f"{r['stars_week']:+d}"
        line = f"#{r['rank']:<3}{move_txt:>4}  {r['repo']:<40} *{_fmt_count(r['stars']):>6} ({stars_week})"
        if r["downloads_week"] is not None:
            change = "" if r["downloads_change"] is None else f" {r['downloads_change'] * 100:+.0f}%"
            line += f"  pypi {_fmt_count(r['downloads_week'])}/wk{change}"
        if r["commits_4w"] is not None:
            line += f"  {r['commits_4w']} commits/4wk"
        click.echo(line)
    _print_producthunt(cfg)


def _print_producthunt(cfg: MyGeekyConfig) -> None:
    from . import producthunt
    posts = producthunt.load_state().get("posts") or []
    if not posts:
        if not auth.get_producthunt_token(cfg.github_username):
            click.echo("\nTip: add Product Hunt launches in your field with `mygeeky auth producthunt`.")
        return
    click.echo("\nProduct Hunt launches (your field first):")
    for p in posts:
        mark = "*" if p.get("match") else " "
        click.echo(f" {mark} {p['votes']:>5} ▲  {p['name']} - {p['tagline'][:70]}")
        click.echo(f"           {p['url']}")


# --------------------------------------------------------------------------- research trends
@main.command()
@click.option("--refresh", is_flag=True, help="Ask OpenAlex again now instead of using the saved trends.")
@click.option("--json", "as_json", is_flag=True)
def trends(refresh: bool, as_json: bool) -> None:
    """Research trends in your field: rising papers, tools with papers, and who leads them."""
    from . import papers
    cfg = load_config()
    state = papers.refresh_trends(cfg, force=refresh, log=lambda m: click.echo(f"[mygeeky] {m}", err=True))
    if as_json:
        click.echo(json.dumps(state, indent=2))
        return
    if state.get("topics"):
        click.echo("Your topics: " + ", ".join(t["name"] for t in state["topics"]) + "\n")
    if state.get("rising"):
        click.echo("Rising in your field (citations per month):")
        for p in state["rising"]:
            tag = " [new territory]" if p.get("explore") else ""
            code = f"  code: {p['repos'][0]}" if p.get("repos") else ""
            click.echo(f"  {p.get('velocity', 0):6.1f}/mo  {p['title'][:90]}{tag}")
            click.echo(f"            {p['url']}{code}")
    if state.get("tools"):
        click.echo("\nTools with papers (code on GitHub):")
        for p in state["tools"]:
            click.echo(f"  [P] {', '.join(p['repos'][:2]):<40} {p['title'][:70]}")
    if state.get("people"):
        click.echo("\nPeople behind the trends:")
        for a in state["people"]:
            click.echo(f"  {a['name']:<32} {a['papers']} trending paper(s), {a['citations']} citations  {a['url']}")


# --------------------------------------------------------------------------- news & interests
@main.command()
@click.option("--refresh", is_flag=True, help="Fetch again now instead of using the saved news.")
@click.option("--json", "as_json", is_flag=True)
def news(refresh: bool, as_json: bool) -> None:
    """New papers and discussions about your interests (arXiv, bioRxiv, Hacker News)."""
    from . import news as news_mod
    cfg = load_config()
    state = news_mod.refresh(cfg, force=refresh, log=lambda m: click.echo(f"[mygeeky] {m}", err=True))
    items = state.get("items") or []
    if as_json:
        click.echo(json.dumps(items, indent=2))
        return
    if not items:
        click.echo("No news yet. Try `mygeeky news --refresh`.")
        return
    for it in items:
        tag = "new territory" if it.get("explore") else ", ".join(it.get("match") or [])
        click.echo(f"  [{news_mod.SOURCE_LABELS.get(it['source'], it['source'])}] {it['title'][:100]}")
        click.echo(f"      {tag} | {it['url']}")
    if state.get("errors"):
        click.echo(f"\n(Couldn't reach: {', '.join(state['errors'])}.)", err=True)


@main.command("interests")
@click.option("--reset", is_flag=True, help="Forget everything learned from your clicks, follows, stars and forks.")
def interests_cmd(reset: bool) -> None:
    """What myGeeKy has learned you're into lately, and today's new territory."""
    from . import interests
    from .config import INTEREST_EVENTS_FILE
    cfg = load_config()
    if reset:
        if click.confirm("Forget everything learned from what you clicked, followed, starred and forked?",
                         default=False):
            INTEREST_EVENTS_FILE.unlink(missing_ok=True)
            click.echo("Done. Your stated interests (CV, papers, topics) are untouched.")
        return
    learned = interests.learned_terms(cfg, 15)
    if not cfg.interest_learning:
        click.echo("Learning is off (`mygeeky config set interest_learning true` turns it on).")
    elif learned:
        click.echo("Learned from what you do lately (strongest first):")
        for term, weight in learned:
            click.echo(f"  {term:<30} {'#' * min(30, max(1, int(weight * 3)))}")
    else:
        click.echo("Nothing learned yet: click people, repos and news in the panel, or follow, star and "
                   "fork on GitHub.")
    share = int(round(cfg.explore_share * 100))
    if share:
        click.echo(f"\nNew territory today ({share}% of every list): {', '.join(interests.explore_terms(cfg, 3))}")


# --------------------------------------------------------------------------- 💡 ideas
@main.command()
@click.argument("title")
@click.option("--kind", type=click.Choice(["idea", "problem", "question"]), default="idea", show_default=True)
@click.option("--details", default="", help="More about it.")
@click.option("--no-version", is_flag=True, help="Don't include the myGeeKy/Python/OS versions.")
def idea(title: str, kind: str, details: str, no_version: bool) -> None:
    """Send an idea, a problem or a question to myGeeKy's maker (opens a prefilled GitHub issue)."""
    from . import ideas
    url = ideas.issue_url(kind, title, details, include_version=not no_version)
    click.echo("Opening it on GitHub: click 'Submit new issue' there to send it (it's public).")
    click.echo(url)
    click.launch(url)


# --------------------------------------------------------------------------- 🛡 admin (the maker only)
@main.group("admin")
def admin_cmd() -> None:
    """The maker's tools: ideas inbox, people to invite, adoption."""


def _require_admin(cfg: MyGeekyConfig) -> None:
    from . import admin
    if not admin.is_admin(cfg):
        raise click.ClickException("These commands are for myGeeKy's maker.")


@admin_cmd.command("inbox")
def admin_inbox() -> None:
    """Newest ideas, problems and questions."""
    from . import ideas
    cfg = load_config()
    _require_admin(cfg)
    for i in ideas.inbox(_client_for(cfg)):
        click.echo(f"  {ideas.KINDS[i['kind']][0]} #{i['number']:<4} {i['title'][:80]}  ({i['author']}, "
                   f"{i['created_at'][:10]}, {i['comments']} comments)")


@admin_cmd.command("prospects")
@click.option("--refresh", is_flag=True, help="Look again (a minute or two).")
def admin_prospects(refresh: bool) -> None:
    """People most likely to want myGeeKy (you invite them yourself)."""
    from . import admin
    cfg = load_config()
    _require_admin(cfg)
    state = admin.refresh_prospects(_client_for(cfg), cfg) if refresh else admin.load()
    for p in admin.prospects(state):
        reach = p.get("email") or "(no public email)"
        click.echo(f"  {p['score']:4.1f}  {p['login']:<22} {reach:<32} {'; '.join(p.get('why', [])[:2])[:60]}")
    f = admin.funnel(state)
    click.echo(f"\nInvited {f['invited']}, joined {f['joined']}, declined {f['declined']}. "
               f"Mark with `mygeeky admin mark <login> invited|declined`.")


@admin_cmd.command("mark")
@click.argument("login")
@click.argument("status", type=click.Choice(["invited", "declined", "new"]))
def admin_mark(login: str, status: str) -> None:
    from . import admin
    _require_admin(load_config())
    result = admin.mark(login, status)
    click.echo(f"{login}: {status}" if result["ok"] else result["message"])


@admin_cmd.group("keywords")
def admin_keywords() -> None:
    """The keyword dictionary: what people asked for, and rebuilding it."""


@admin_keywords.command("requests")
def admin_keywords_requests() -> None:
    """Keywords the dictionary doesn't know yet (from beacons and suggestions)."""
    cfg = load_config()
    _require_admin(cfg)
    rows = keywords.keyword_requests(_client_for(cfg), cfg)
    if not rows:
        click.echo("No unknown keywords yet.")
    for r in rows:
        click.echo(f"  {r['word']:<30} on Signals: {r['people']:<3} suggested: {r['suggested']}")


@admin_keywords.command("build")
@click.option("--max-terms", default=300, show_default=True, help="Keywords to learn (one search call each).")
@click.option("--no-requests", is_flag=True, help="Don't add the requested keywords to the seeds.")
@click.option("--out", type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="Where to write it (default: the package's data/keywords.json).")
def admin_keywords_build(max_terms: int, no_requests: bool, out: Path | None) -> None:
    """Rerun the model on GitHub's open data and write a new dictionary."""
    cfg = load_config()
    _require_admin(cfg)
    client = _client_for(cfg)
    extra = [] if no_requests else [r["word"] for r in keywords.keyword_requests(client, cfg)]
    if extra:
        click.echo(f"Including {len(extra)} requested keyword(s): {', '.join(extra[:12])}")
    click.echo(f"Learning up to {max_terms} keywords (about {max_terms * 5.5 / 60:.0f} minutes)...")
    d = keywords.build(client, extra=extra, max_terms=max_terms, log=lambda m: click.echo(f"[mygeeky] {m}", err=True))
    path = keywords.save(d, out or keywords.BUNDLED)
    taught = [w for w in extra if keywords.known(w)]
    click.echo(f"Wrote {path}: {len(d['terms'])} keywords, version {d['version']}.")
    if extra:
        click.echo(f"Learned {len(taught)} of the {len(extra)} requested: {', '.join(taught) or '-'} "
                   "(the others have too few repos on GitHub to learn from yet).")
    click.echo("Publish it: commit data/keywords.json and push (everyone picks it up within a week).")


@admin_cmd.command("stats")
def admin_stats() -> None:
    """Adoption: PyPI downloads, installer downloads, stars, forks, Signals users."""
    from . import admin
    cfg = load_config()
    _require_admin(cfg)
    for k, v in admin.adoption(_client_for(cfg)).items():
        click.echo(f"  {k:<22} {'-' if v is None else v}")


@main.command("headlines")
@click.option("--refresh", is_flag=True, help="Read the feeds again now.")
@click.option("--json", "as_json", is_flag=True)
def headlines_cmd(refresh: bool, as_json: bool) -> None:
    """What's happening across your work, as titles: AI labs, journals and the tech press, ranked for you."""
    from . import headlines as hl
    cfg = load_config()
    state = hl.refresh(cfg, force=refresh, log=lambda m: click.echo(f"[mygeeky] {m}", err=True))
    items = state.get("items") or []
    if as_json:
        click.echo(json.dumps(items, indent=2))
        return
    if not items:
        click.echo("No headlines yet: `mygeeky headlines --refresh`.")
    for label, group in (("For your work", [x for x in items if not x.get("explore")]),
                         ("The big picture", [x for x in items if x.get("explore")])):
        if group:
            click.secho(f"\n{label}", bold=True)
        for x in group:
            click.echo(f"  {x['source'][:16]:<16} {x['title']}")


# --------------------------------------------------------------------------- keywords
@main.group("keywords", invoke_without_command=True)
@click.pass_context
def keywords_cmd(ctx: click.Context) -> None:
    """Your keywords. Green ones mean something (the dictionary knows what goes
    with them); red ones are plain words for now."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(keywords_list)


@keywords_cmd.command("list")
def keywords_list() -> None:
    """Your keywords, green (known) or red (plain words for now)."""
    cfg = load_config()
    if not cfg.keywords:
        click.echo("No keywords yet: `mygeeky keywords add \"single cell\" AI`.")
    for word in cfg.keywords:
        entry = keywords.lookup(word)
        if entry:
            rel = ", ".join(keywords.label_of(r) for r, _ in entry["related"][:6])
            click.secho(f"  ● {word}", fg="green", nl=False)
            click.echo(f"   also: {rel}")
        else:
            click.secho(f"  ● {word}", fg="red", nl=False)
            click.echo("   plain word for now (`mygeeky keywords suggest` sends it to the maker)")
    click.echo(f"\nDictionary version {keywords.load().get('version') or '-'}, "
               f"{len(keywords.load()['terms'])} keywords.")


def _set_keywords(words: list[str]) -> None:
    from .gui.app import set_keywords
    result = set_keywords(load_config(), words)
    if result.get("note"):
        click.echo(result["note"])


@keywords_cmd.command("add")
@click.argument("words", nargs=-1, required=True)
def keywords_add(words: tuple[str, ...]) -> None:
    """Add keywords (quote ones with spaces)."""
    cfg = load_config()
    _set_keywords(list(cfg.keywords) + list(words))
    for w in words:
        if keywords.known(w):
            click.secho(f"  ● {w}: known", fg="green")
        else:
            click.secho(f"  ● {w}: not in the dictionary yet, used as a plain word", fg="red")
    keywords_list.callback()


@keywords_cmd.command("remove")
@click.argument("words", nargs=-1, required=True)
def keywords_remove(words: tuple[str, ...]) -> None:
    """Remove keywords."""
    drop = {w.lower() for w in words}
    _set_keywords([w for w in load_config().keywords if w.lower() not in drop])
    keywords_list.callback()


@keywords_cmd.command("explain")
@click.argument("word")
def keywords_explain(word: str) -> None:
    """What WORD means to myGeeKy."""
    entry = keywords.lookup(word)
    if not entry:
        click.echo(f"'{word}' isn't in the dictionary yet: it's matched as a plain word.")
        return
    click.echo(f"{word} -> {entry['label']} ({entry.get('repos', '?')} repos read). Goes with:")
    for rel, w in entry["related"]:
        click.echo(f"  {w:5.2f}  {keywords.label_of(rel)}")


@keywords_cmd.command("suggest")
@click.argument("word")
def keywords_suggest(word: str) -> None:
    """Ask for WORD to join the dictionary (opens a prefilled GitHub issue you submit)."""
    from . import ideas
    url = ideas.keyword_url(word)
    click.echo("Opening it on GitHub: click 'Submit new issue' there to send it.")
    click.launch(url)


@keywords_cmd.command("update")
def keywords_update() -> None:
    """Fetch the newest keyword dictionary now."""
    from .config import DATA_DIR  # noqa: F401
    cached = keywords.CACHE_FILE
    if cached.exists():
        cached.unlink()
    changed = keywords.refresh_if_due()
    click.echo(f"Dictionary version {keywords.load().get('version')}" + (" (updated)" if changed else " (up to date)"))


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
    if not sync_mod._has_gh() and sync_mod.public_on_github(repo) is False and not sync_mod._repo_exists(repo):
        click.echo("\nFirst, create it on GitHub (only you will be able to see it):")
        for i, step in enumerate(sync_mod.create_steps(repo), 1):
            click.echo(f"  {i}. {step}")
        click.launch(sync_mod.new_repo_url(repo))
        click.echo("\nmyGeeKy writes your data there with your own Git login (Git may ask you to sign in to GitHub\n"
                   "the first time). Your read-only myGeeKy token is never used for it.")
        click.pause("\nPress any key once you've created it...")
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


# --------------------------------------------------------------------------- beacon
@main.group()
def beacon() -> None:
    """Private, non-verbal signals between myGeeKy users: 🙏 thanks, 📚 learned
    from your work, ⭐ used your work, 👀 following, 🤝 collaborate (shown only
    if you both choose it). Only the recipient can read a signal; no reply is
    ever expected."""


def _beacon_call(fn, *args, **kwargs):
    from . import beacon as bc
    try:
        return fn(*args, **kwargs)
    except bc.BeaconError as exc:
        raise click.ClickException(str(exc)) from exc


@beacon.command("init")
def beacon_init() -> None:
    """Create your public beacon repo, store its write token, and publish."""
    import shutil
    from . import beacon as bc
    cfg = load_config()
    if not cfg.github_username:
        raise click.ClickException("Run `mygeeky init` first.")
    repo = f"{cfg.github_username}/{bc.BEACON_REPO}"
    click.echo(f"Beacons live in a PUBLIC repo, {repo}. Anyone can see the signals you send,\n"
               "who you send them to, your status and your interest tags. Signals are emoji only,\n"
               "never text. myGeeKy writes only beacon.json/README.md there, with a token scoped to that repo.\n")
    client = _client_for(cfg)
    user = cfg.github_username

    # Step 1: the public repo
    click.secho("\nStep 1 of 3: your public beacon repo", bold=True)
    if client.get_repo(repo) is None:
        if shutil.which("gh") and click.confirm(f"Create the public repo {repo} with the GitHub CLI now?",
                                                default=True):
            for note in _beacon_call(bc.ensure_repo, cfg, client, create=True):
                click.echo(note)
        else:
            _show_steps(bc.repo_steps(user))
            if click.confirm("Open that page in your browser now?", default=True):
                click.launch(bc.NEW_REPO_URL)
            while client.get_repo(repo) is None:
                if not click.confirm(f"\nI can't see {repo} yet. Created it? Press Enter to check again "
                                     "(or answer n to stop)", default=True):
                    return
    for note in _beacon_call(bc.ensure_repo, cfg, client, create=False):
        click.echo(note)
    click.secho(f"  ✓ {repo} exists and is public.", fg="green")

    # Step 2: a token that can write to that one repo, tested by really publishing
    click.secho("\nStep 2 of 3: a second token, that can write to that repo only", bold=True)
    token = auth.get_beacon_token(user)
    for attempt in range(3):
        if not token:
            _show_steps(bc.token_steps(user))
            if attempt == 0 and click.confirm("Open that page in your browser now?", default=True):
                click.launch(bc.TOKEN_URL)
            token = click.prompt("\nPaste the token (input hidden)", hide_input=True).strip()
        from . import token_check
        verdict = token_check.check("beacon", token, user, other_token=auth.get_token(user))
        for msg in verdict["warnings"]:
            click.secho(f"  ! {msg}", fg="yellow")
        if not verdict["ok"]:
            for msg in verdict["errors"]:
                click.secho(f"  ✗ {msg}", fg="red")
            token = None
            continue
        try:
            bc.go_live(cfg, bc.BeaconWriter(token, user))
        except bc.BeaconError as exc:
            click.secho(f"  ✗ {exc}", fg="red")
            click.echo("  Check the token's settings against the steps above, generate a new one, and paste it.")
            token = None
            continue
        import keyring
        keyring.set_password(auth.BEACON_SERVICE_NAME, user, token)
        from . import tokens
        tokens.forget()
        click.secho("  ✓ The token works. It's stored in your OS keyring.", fg="green")
        break
    else:
        raise click.ClickException("Signals aren't set up yet. Run `mygeeky beacon init` again when ready.")

    # Step 3: read it back, the way everyone else will
    click.secho("\nStep 3 of 3: checking that others can see you", bold=True)
    if bc.fetch_beacon(client, user) is None:
        click.echo("  beacon.json was written, but GitHub isn't showing it yet. Give it a minute, then run "
                   "`mygeeky beacon check`.")
    else:
        click.secho(f"  ✓ beacon.json is published at https://github.com/{repo}", fg="green")
    click.echo(f"\nYour beacon is live: https://github.com/{repo}\n"
               "Try `mygeeky beacon people` to see who else is here, then "
               "`mygeeky beacon send <user> wave`.")


def _show_steps(steps: list[str]) -> None:
    n = 0
    for line in steps:
        if line.startswith("  "):
            click.echo(f"     {line.strip()}")
        else:
            n += 1
            click.echo(f"  {n}. {line}")


@beacon.command("check")
def beacon_check() -> None:
    """Find out what's missing if Signals isn't working (changes nothing)."""
    from . import beacon as bc
    cfg = load_config()
    results = bc.check(cfg, _client_for(cfg))
    for ok, message in results:
        click.secho(f"  {'✓' if ok else '✗'} {message}", fg="green" if ok else "red")
    if all(ok for ok, _ in results):
        click.echo("\nAll good. Others see your beacon; click Refresh on the Signals tab to see theirs.")


def _beacon_cache(cfg: MyGeekyConfig, refresh: bool) -> dict:
    from . import beacon as bc
    return bc.refresh(_client_for(cfg), cfg, force=refresh, log=lambda m: click.echo(f"[mygeeky] {m}", err=True))


@beacon.command("send")
@click.argument("user")
@click.argument("gesture", type=click.Choice(["thanks", "learn", "used", "watching", "collab"]))
@click.option("--repo", default=None, help="owner/name -- the repo you used (for 'used').")
def beacon_send(user: str, gesture: str, repo: str | None) -> None:
    """Send USER a private signal: thanks, learn, watching, collab, or used --repo owner/name."""
    from . import beacon as bc
    cfg = load_config()
    _beacon_call(bc.send, cfg, user, gesture, repo, cache=_beacon_cache(cfg, refresh=False))
    emoji = bc.GESTURES[gesture][0]
    if gesture in bc.MUTUAL_ONLY:
        click.echo(f"{emoji} noted. {user} only finds out if they choose it for you too; then you both see it.")
    else:
        click.echo(f"{emoji} sent privately to {user}: only they can read it, and no reply is expected.")


@beacon.command("unsend")
@click.argument("user")
@click.argument("gesture", required=False)
def beacon_unsend(user: str, gesture: str | None) -> None:
    """Take back your signals to USER (all of them, or just GESTURE). They disappear from your beacon."""
    from . import beacon as bc
    n = _beacon_call(bc.unsend, load_config(), user, gesture)
    click.echo(f"Removed {n} signal(s) to {user}." if n else f"You haven't signalled {user}.")


@beacon.command("inbox")
@click.option("--refresh", is_flag=True, help="Re-read everyone's beacons now.")
@click.option("--json", "as_json", is_flag=True)
def beacon_inbox(refresh: bool, as_json: bool) -> None:
    """Signals other myGeeKy users sent you (no reply is ever expected)."""
    from . import beacon as bc
    cfg = load_config()
    cache = _beacon_cache(cfg, refresh)
    _beacon_call(bc.ensure_published, cfg)
    rows = bc.inbox(cache, cfg, bc.load_my_beacon(), bc.private_key_or_none(cfg))
    if as_json:
        click.echo(json.dumps(rows, indent=2))
        return
    if cfg.beacon_quiet:
        click.echo(f"You're not taking signals right now ({len(rows)} waiting). "
                   "`mygeeky beacon quiet off` when you're back.")
        return
    if not rows:
        click.echo("Nothing yet. Signals are small thank-yous; see `mygeeky beacon people`.")
        return
    for r in rows:
        click.echo(f"  {r['from']:<25} {r['text']}  ({r['at'][:10]})")


@beacon.command("people")
@click.option("--refresh", is_flag=True, help="Re-read everyone's beacons now.")
@click.option("--json", "as_json", is_flag=True)
def beacon_people(refresh: bool, as_json: bool) -> None:
    """Fellow myGeeKy users, those sharing your interests first."""
    from . import beacon as bc
    cfg = load_config()
    rows = bc.people(_beacon_cache(cfg, refresh), cfg, bc.load_my_beacon(), private_key=bc.private_key_or_none(cfg))
    if as_json:
        click.echo(json.dumps(rows, indent=2))
        return
    if not rows:
        click.echo("No other beacons found yet.")
        return
    for p in rows:
        marks = ("📨 " if p["signalled_you"] else "") + ("✓ " if p["you_signalled"] else "")
        note = "" if p["can_receive"] or p["quiet"] else "  (older myGeeKy: can't receive yet)"
        click.echo(f"  {marks}{p['login']:<25} {p['status']}{note}")
        if p["shared"]:
            click.echo(f"      shares: {', '.join(p['shared'])}")


@beacon.command("sent")
def beacon_sent() -> None:
    """The signals you've sent. Only you see this list; your beacon holds them sealed."""
    from . import beacon as bc
    sent = bc.load_my_beacon()["sent"]
    if not sent:
        click.echo("You haven't sent any signals.")
    for g in sorted(sent, key=lambda g: g.get("at", ""), reverse=True):
        repo = f" ({g['repo']})" if g.get("repo") else ""
        emoji = (bc.GESTURES.get(g.get("type")) or bc.LEGACY_GESTURES.get(g.get("type")) or ("·",))[0]
        click.echo(f"  {emoji} {g.get('type', ''):<9} -> {g.get('to', '')}{repo}  {g.get('at', '')[:10]}  sent ✓")


@beacon.command("status")
@click.argument("value", required=False)
def beacon_status(value: str | None) -> None:
    """Show or set your status (open-to-collab, learning, heads-down,
    seeking-reviewers, mentoring, or "none")."""
    from . import beacon as bc
    cfg = load_config()
    if value is None:
        click.echo(f"Status: {bc.STATUSES.get(cfg.beacon_status) or '(none)'}")
        click.echo("Choices: " + ", ".join(k for k in bc.STATUSES if k) + ", none")
        return
    value = "" if value == "none" else value
    if value not in bc.STATUSES:
        raise click.ClickException("Choose one of: " + ", ".join(k for k in bc.STATUSES if k) + ", none")
    cfg.beacon_status = value
    _beacon_call(bc.publish, cfg, bc.load_my_beacon())
    save_config(cfg)
    click.echo(f"Status: {bc.STATUSES[value] or '(none)'}")


@beacon.command("quiet")
@click.argument("state", type=click.Choice(["on", "off"]), required=False)
def beacon_quiet(state: str | None) -> None:
    """Not taking signals right now? `quiet on` (others can't send to you; nobody is told why)."""
    from . import beacon as bc
    cfg = load_config()
    if state is None:
        click.echo(f"Quiet: {'on' if cfg.beacon_quiet else 'off'}")
        return
    _beacon_call(bc.set_quiet, cfg, state == "on")
    click.echo("You're not taking signals for now." if state == "on" else "You're taking signals again.")


@beacon.command("mute")
@click.argument("user")
def beacon_mute(user: str) -> None:
    """Hide USER's signals. They're never told (block also stops yours to them)."""
    from . import beacon as bc
    bc.set_muted(load_config(), user, True)
    click.echo(f"Muted {user}.")


@beacon.command("unmute")
@click.argument("user")
def beacon_unmute(user: str) -> None:
    """Show USER's signals again."""
    from . import beacon as bc
    bc.set_muted(load_config(), user, False)
    click.echo(f"Unmuted {user}.")


@beacon.command("block")
@click.argument("user")
def beacon_block(user: str) -> None:
    """Never show signals from USER again (and drop yours to them)."""
    from . import beacon as bc
    cfg = load_config()
    if user.lower() not in {u.lower() for u in cfg.beacon_blocked}:
        cfg.beacon_blocked.append(user)
        save_config(cfg)
    if cfg.beacon_enabled:
        _beacon_call(bc.unsend, cfg, user)
    click.echo(f"Blocked {user}.")


@beacon.command("unblock")
@click.argument("user")
def beacon_unblock(user: str) -> None:
    """Show signals from USER again."""
    cfg = load_config()
    cfg.beacon_blocked = [u for u in cfg.beacon_blocked if u.lower() != user.lower()]
    save_config(cfg)
    click.echo(f"Unblocked {user}.")


@beacon.command("publish")
def beacon_publish() -> None:
    """Re-publish your beacon, after changing your topics or keywords."""
    from . import beacon as bc
    _beacon_call(bc.publish, load_config(), bc.load_my_beacon())
    click.echo("Beacon published.")


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


# --------------------------------------------------------------------------- setup
@main.command()
def setup() -> None:
    """Open the setup wizard: update, reconnect GitHub, sync, Signals, shortcuts."""
    from .gui.bootstrap import ensure_qt
    ensure_qt()
    from .gui.setup_wizard import main as setup_main
    setup_main([])


# --------------------------------------------------------------------------- gui
@main.command()
@click.option("--foreground", is_flag=True, help="Run in this terminal (for troubleshooting).")
def gui(foreground: bool) -> None:
    """Open the panel. It runs in the background: you can close this terminal."""
    import sys
    from .config import LOG_DIR
    from .gui import desktop
    from .gui.bootstrap import ensure_qt
    if foreground:
        from .gui.app import main as gui_main
        gui_main()
        return
    ensure_qt()                      # the first time, this installs Qt here, where you can see it
    if _panel_running():
        click.echo("myGeeKy is already running (look for its icon on the edge of your screen).")
        return
    if sys.platform.startswith("linux"):
        for line in desktop.install_menu_entry():
            click.echo(line)
    desktop.launch_detached(LOG_DIR / "panel.log")
    click.echo("myGeeKy is running in the background: look for its icon on the edge of your screen. "
               "You can close this terminal. (Quit it from ⚙ in the panel.)")


def _panel_running() -> bool:
    """Is a panel already open? (It holds a lock while it runs.)"""
    try:
        from PySide6.QtCore import QLockFile
        from .config import DATA_DIR, ensure_dirs
        ensure_dirs()
        lock = QLockFile(str(DATA_DIR / "panel.lock"))
        if lock.tryLock(0):
            lock.unlock()
            return False
        return True
    except Exception:
        return False


@main.group("desktop")
def desktop_cmd() -> None:
    """Linux: myGeeKy in your applications menu, and (optionally) at sign-in."""


@desktop_cmd.command("install")
@click.option("--autostart/--no-autostart", default=None, help="Also open it when you sign in (or stop that).")
def desktop_install(autostart: bool | None) -> None:
    """Add myGeeKy (with its icon) to your applications menu."""
    import sys
    from .gui import desktop
    if not sys.platform.startswith("linux"):
        raise click.ClickException("This is for Linux. On Windows, the installer adds the Start-menu entry.")
    changed = desktop.install_menu_entry(autostart=autostart)
    click.echo("\n".join(changed) or "Already in your applications menu.")


@desktop_cmd.command("remove")
def desktop_remove() -> None:
    """Take myGeeKy out of the applications menu and sign-in."""
    from .gui import desktop
    removed = desktop.remove_menu_entry()
    click.echo(f"Removed {len(removed)} file(s)." if removed else "Nothing to remove.")


if __name__ == "__main__":
    main()
