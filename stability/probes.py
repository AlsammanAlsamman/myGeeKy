"""myGeeKy stability probes: each one deliberately triggers a failure that apps
built like myGeeKy are known to hit (see PROTOCOL.md), and records what happens.

Safety: every probe runs in its own child process with a throwaway data and
config folder (platformdirs is redirected before myGeeKy is imported) and a
null keyring, so your real settings, tokens and synced repo are never read or
written. Nothing touches the network except local fake servers.

    python stability/probes.py            # run all, write stability/REPORT.md
    python stability/probes.py --one NAME # run one (used by the runner)
"""

from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PROBES: dict[str, dict] = {}


def probe(id_: str, area: str, title: str, platforms: str = "all", timeout: int = 90):
    def deco(fn):
        PROBES[fn.__name__] = {"id": id_, "area": area, "title": title, "fn": fn,
                               "platforms": platforms, "timeout": timeout}
        return fn
    return deco


def result(status: str, observed: str, fix: str = "") -> dict:
    """status: PASS (handled), FAIL (a user would hit it), WARN (degraded, not broken)."""
    return {"status": status, "observed": observed, "fix": fix}


# ----------------------------------------------------------------------------- isolation (child process)
def _isolate() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="mygeeky-probe-"))
    import platformdirs
    platformdirs.user_data_dir = lambda *a, **k: str(tmp / "data")
    platformdirs.user_config_dir = lambda *a, **k: str(tmp / "config")
    os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    sys.path.insert(0, str(ROOT / "src"))
    import mygeeky.config as config
    assert str(config.DATA_DIR).startswith(str(tmp)), "isolation failed: refusing to run"
    config.ensure_dirs()
    return tmp


# ----------------------------------------------------------------------------- data files
@probe("D1", "Data files", "A half-written config.json (crash or power cut during a save)")
def corrupt_config():
    from mygeeky import config
    config.save_config(config.MyGeekyConfig(github_username="probe-user"))
    config.save_config(config.MyGeekyConfig(github_username="probe-user", gui_theme="aurora"))   # a later change
    text = config.CONFIG_FILE.read_text(encoding="utf-8")
    config.CONFIG_FILE.write_text(text[: len(text) // 2], encoding="utf-8")
    try:
        cfg = config.load_config()
    except Exception as exc:
        return result("FAIL", f"load_config() raised {type(exc).__name__}: the panel would not start at all "
                      "(start-up error box), until the user finds and deletes config.json by hand.",
                      "Write config atomically (temp file + os.replace) and, when it can't be read, fall back to "
                      "the newest config.backup-*.json / config.synced.json with a notice.")
    kept = list(config.CONFIG_FILE.parent.glob("config.json.broken-*"))
    if cfg.github_username != "probe-user":
        return result("FAIL", f"the panel starts, but with settings reset (user={cfg.github_username!r}, restored from "
                      f"{config.RECOVERED_FROM}).", "Keep the previous good version on every save and recover from it.")
    return result("PASS", f"started with the settings restored from {config.RECOVERED_FROM} (user kept); the damaged "
                  f"file was kept aside ({len(kept)} file); config.json is readable again: "
                  f"{config._readable(config.CONFIG_FILE) is not None}")


@probe("D1b", "Data files", "Killed in the middle of saving config.json, 40 times", timeout=180)
def kill_during_save():
    from mygeeky import config
    code = ("import sys, platformdirs; d=sys.argv[1]; "
            "platformdirs.user_data_dir=lambda *a,**k: d+'/data'; platformdirs.user_config_dir=lambda *a,**k: d+'/config'; "
            "sys.path.insert(0, sys.argv[2]); from mygeeky import config; "
            "c=config.MyGeekyConfig(github_username='probe-user', keywords=['x'*400]*40)\n"
            "while True: config.save_config(c)")
    tmp = str(config.DATA_DIR.parent)
    import dataclasses
    assert "keywords" in {f.name for f in dataclasses.fields(config.MyGeekyConfig)}, "probe uses an unknown setting"
    config.save_config(config.MyGeekyConfig(github_username="probe-user"))   # a good file to start from
    broken = 0
    for i in range(40):
        p = subprocess.Popen([sys.executable, "-c", code, tmp, str(ROOT / "src")])
        time.sleep(0.25 + (i % 7) * 0.013)
        p.kill(); p.wait()
        try:
            json.loads(config.CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            broken += 1
    if broken:
        return result("FAIL", f"{broken} of 40 kills left an unreadable config.json (so the next start fails, see D1).",
                      "Atomic write: write config.json.tmp, flush + fsync, then os.replace.")
    return result("PASS", "0 of 40 kills left a broken file")


@probe("D4", "Data files", "config.json saved with a BOM by a text editor (Notepad, PowerShell 5)")
def bom_config():
    from mygeeky import config
    config.save_config(config.MyGeekyConfig(github_username="probe-user"))
    raw = config.CONFIG_FILE.read_text(encoding="utf-8")
    config.CONFIG_FILE.write_bytes(b"\xef\xbb\xbf" + raw.encode("utf-8"))
    try:
        config.load_config()
    except Exception as exc:
        return result("FAIL", f"load_config() raised {type(exc).__name__} ({str(exc)[:60]}): panel won't start.",
                      "Read JSON files with encoding='utf-8-sig'.")
    return result("PASS", "a BOM is accepted")


@probe("D2", "Data files", "One half-written line in a history file (.jsonl)")
def partial_jsonl():
    from mygeeky import storage, config
    storage.log_suggestions([{"username": "a", "list_type": "people", "score": 1,
                              "suggested_at": datetime.now().isoformat()}])
    with open(config.SUGGESTIONS_LOG, "a", encoding="utf-8") as fh:
        fh.write('{"username": "b", "sco')           # the process died mid-line
    try:
        rows = storage.read_jsonl(config.SUGGESTIONS_LOG)
    except Exception as exc:
        return result("FAIL", f"read_jsonl() raised {type(exc).__name__}: every reader of that file (suggestions, "
                      "training data, model history, contributions) fails until the line is removed by hand.",
                      "Skip (and count) unreadable lines in read_jsonl and the other .jsonl readers.")
    return result("PASS", f"read {len(rows)} good row(s), skipped the broken one")


@probe("D3", "Data files", "Every other saved state file, half-written")
def other_state_files():
    from mygeeky import config, storage, beacon, headlines, admin, interests, hfmodels, news
    loaders = {
        "excluded.json": (config.EXCLUDED_FILE, storage.load_excluded),
        "following_snapshot.json": (config.FOLLOWING_SNAPSHOT, storage.load_following_snapshot),
        "activity_cache.json": (config.ACTIVITY_CACHE_FILE, storage.load_activity_cache),
        "beacon.json": (config.MY_BEACON_FILE, beacon.load_my_beacon),
        "beacons_cache.json": (config.BEACON_CACHE_FILE, beacon.load_cache),
        "headlines.json": (config.HEADLINES_FILE, headlines.load_state),
        "admin_prospects.json": (config.ADMIN_FILE, admin.load),
        "interest_events.jsonl": (config.INTEREST_EVENTS_FILE, interests.load_events),
        "interest_seen.json": (config.INTEREST_SEEN_FILE, interests._load_seen),
        "hf_models.json": (config.HF_MODELS_FILE, hfmodels.load_state),
        "news.json": (config.NEWS_FILE, news.load_state),
    }
    bad = []
    for name, (path, load) in loaders.items():
        path.write_text('{"half": [1, 2', encoding="utf-8")
        try:
            load()
        except Exception as exc:
            bad.append(f"{name} ({type(exc).__name__})")
    if bad:
        return result("FAIL", f"{len(bad)} of {len(loaders)} loaders raise on a half-written file: " + ", ".join(bad),
                      "One shared helper: read_json(path, default) that returns the default on a bad file, "
                      "and an atomic write_json used for every state file.")
    return result("PASS", f"all {len(loaders)} loaders fall back to empty")


# ----------------------------------------------------------------------------- git sync
@probe("G1", "Sync (git)", "The sync server stops answering (stalled network, proxy, captive portal)", timeout=200)
def git_hang():
    from mygeeky import sync, config
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(5)
    port = srv.getsockname()[1]
    conns = []
    threading.Thread(target=lambda: [conns.append(srv.accept()) for _ in range(5)], daemon=True).start()
    box: dict = {}

    def run():
        t0 = time.time()
        try:
            sync._git("ls-remote", f"http://127.0.0.1:{port}/me/mygeeky-data.git", cwd=config.DATA_DIR, check=False)
        except Exception as exc:
            box["exc"] = exc
        box["took"] = time.time() - t0
    t = threading.Thread(target=run, daemon=True); t.start(); t.join(150)
    stuck = t.is_alive()
    srv.close()
    for c, _ in conns:
        c.close()
    t.join(10)
    if stuck:
        return result("FAIL", "git was still waiting after 150 s and had no timeout of its own: \"Syncing...\" "
                      "would stay forever and the sync worker never returns.",
                      "Give _git() a timeout (e.g. 120 s) plus http.lowSpeedLimit/lowSpeedTime, and report it.")
    return result("PASS", f"git gave up after {box.get('took', 0):.0f} s")


@probe("G1b", "Sync (git)", "git would ask for a password in the background (no saved login)")
def git_prompt_env():
    from mygeeky import sync, winproc
    seen = {}
    real = winproc.run
    def spy(cmd, **kw):
        seen["env"] = kw.get("env")
        return real(["git", "--version"], capture_output=True, text=True)
    winproc.run = spy
    sync._git("status", check=False)
    env = seen.get("env") or {}
    if env.get("GIT_TERMINAL_PROMPT") == "0" and env.get("GCM_INTERACTIVE", "").lower() == "never":
        return result("PASS", "prompts are switched off for background git")
    return result("FAIL", "background git runs with prompts allowed (no GIT_TERMINAL_PROMPT=0 / GCM_INTERACTIVE=never): "
                  "with no saved login, git waits on a hidden prompt or pops a sign-in window during a timed sync.",
                  "Set GIT_TERMINAL_PROMPT=0 and GCM_INTERACTIVE=never for background syncs; keep prompts only "
                  "for the first `sync init` the user runs themselves.")


# ----------------------------------------------------------------------------- network
class _Resp:
    def __init__(self, code=200, body=None, headers=None, text=None):
        self.status_code, self._body, self.headers = code, body, headers or {}
        self.text = text if text is not None else json.dumps(body)
        self.content = self.text.encode()

    def json(self):
        if self._body is None:
            return json.loads(self.text)
        return self._body


@probe("N1", "Network", "GitHub says 'wait an hour' (rate limit used up)")
def rate_limit_wait():
    import time as t
    from mygeeky import github_client
    c = github_client.GitHubClient(token=None)
    c.session.get = lambda *a, **k: _Resp(200, {"login": "x"}, {"X-RateLimit-Remaining": "0",
                                                                 "X-RateLimit-Reset": str(int(t.time()) + 3600)})
    slept = []
    github_client.time.sleep = lambda s: slept.append(s)
    c.get_user("x")
    longest = max(slept or [0])
    if longest > 120:
        return result("FAIL", f"the request thread would sleep {longest/60:.0f} minutes inside _get(): that refresh "
                      "(and quitting while it runs) hangs for an hour with no message.",
                      "Never sleep more than ~60 s; raise a RateLimited error with the reset time and show "
                      "'GitHub limit reached, back at HH:MM'.")
    try:
        c.get_user("y")                          # the next request, still inside GitHub's hour
    except Exception as exc:
        from mygeeky.errors import describe
        return result("PASS", f"no waiting inside a request (longest {longest:.0f} s); the next request says: "
                      f"\"{describe(exc)}\"")
    return result("WARN", f"longest wait {longest:.0f} s, but the next request went ahead inside GitHub's limit")


@probe("N2", "Network", "GitHub's 'slow down' reply (secondary rate limit: 403/429 + Retry-After)")
def secondary_limit():
    from mygeeky import github_client
    c = github_client.GitHubClient(token=None)
    c.session.get = lambda *a, **k: _Resp(403, {"message": "You have exceeded a secondary rate limit"},
                                          {"Retry-After": "60"})
    try:
        user = c.get_user("octocat")
    except Exception as exc:
        return result("PASS", f"raised {type(exc).__name__}: {exc}")
    return result("FAIL", f"get_user() returned {user!r}: the limit looks like 'user not found / nothing new', "
                  "and the next requests keep hitting it.",
                  "Recognise 403/429 with Retry-After or 'rate limit' in the message: back off and say so.")


@probe("N7", "Network", "Work network that inspects HTTPS (Zscaler/Netskope style)")
def tls_message():
    import requests
    from mygeeky.errors import describe
    msg = describe(requests.exceptions.SSLError("certificate verify failed: self-signed certificate in chain"))
    try:
        import truststore  # noqa: F401
        has_truststore = True
    except ImportError:
        has_truststore = False
    misleading = "connection" in msg.lower() and "certificate" not in msg.lower()
    if misleading or not has_truststore:
        return result("FAIL" if misleading else "WARN",
                      f"the user is told: \"{msg}\". Their internet works; Python just doesn't trust the "
                      f"company's certificate (truststore installed: {has_truststore}).",
                      "Use the OS certificate store (`truststore.inject_into_ssl()`, Python 3.10+) and say "
                      "\"your network inspects secure connections\" for SSL errors.")
    return result("PASS", msg)


@probe("N9", "Network", "Hotel/airport Wi-Fi login page instead of GitHub (HTML with status 200)")
def captive_portal():
    from mygeeky import github_client
    c = github_client.GitHubClient(token=None)
    c.session.get = lambda *a, **k: _Resp(200, None, {}, text="<html><body>Please log in to Wi-Fi</body></html>")
    try:
        c.get_user("octocat")
    except github_client.NotGitHub if hasattr(github_client, "NotGitHub") else () as exc:
        from mygeeky.errors import describe
        return result("PASS", f"recognised as a sign-in page; the user is told: \"{describe(exc)}\"")
    except ValueError as exc:
        return result("WARN", f"raised {type(exc).__name__} (a JSON error), shown to the user as "
                      "a confusing technical message rather than 'check your Wi-Fi login'.",
                      "Treat a non-JSON 200 from the API as 'the network returned a web page' (likely a login page).")
    except Exception as exc:
        return result("WARN", f"raised {type(exc).__name__}")
    return result("PASS", "handled")


# ----------------------------------------------------------------------------- Qt / panel
_QT_PRELUDE = r"""
import os, sys, time, dataclasses
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
app = QApplication([])
import requests                      # no real network: every request fails at once, like being offline
def _offline(*a, **k): raise requests.ConnectionError("offline (stability probe)")
requests.Session.request = _offline; requests.get = _offline; requests.post = _offline
import mygeeky.config as config_mod
from mygeeky.gui import app as logic
logic.get_update_info = lambda cfg: {"show": False}
logic.get_token_warnings = lambda cfg: []
logic.sync_enabled = lambda cfg: False
for n in ("news_refresh_due", "trends_due", "market_refresh_due", "hf_models_due"): setattr(logic, n, lambda cfg: False)
from mygeeky.gui.qt_panel import MyGeekyPanel
def wait(t):
    end = time.time() + t
    while time.time() < end: app.processEvents(); time.sleep(0.01)
"""


def _child(code: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run Qt code in a grandchild (same isolation) and capture how it ended."""
    tmp = str(Path(tempfile.mkdtemp(prefix="mygeeky-qt-")))
    head = ("import sys, os, platformdirs; d=sys.argv[1]; "
            "platformdirs.user_data_dir=lambda *a,**k: d+'/data'; platformdirs.user_config_dir=lambda *a,**k: d+'/config'; "
            "os.environ['PYTHON_KEYRING_BACKEND']='keyring.backends.null.Keyring'; sys.path.insert(0, sys.argv[2])\n")
    return subprocess.run([sys.executable, "-c", head + _QT_PRELUDE + code, tmp, str(ROOT / "src")],
                          capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")


@probe("Q9", "Panel (Qt)", "Quitting while background work is still running, 10 times", timeout=240)
def quit_with_workers():
    code = r"""
from mygeeky.gui.qt_panel import _Worker
p = MyGeekyPanel(config_mod.MyGeekyConfig(github_username="probe-user")); p.show(); wait(0.3)
ws = [_Worker(lambda: time.sleep(1.5)) for _ in range(4)]
for w in ws: w.start()
wait(0.1)
p.close(); del p
ws = None                         # the caller drops its references, as the panel does
app.quit()
import gc; gc.collect()
from mygeeky.gui.qt_panel import _Worker
if _Worker.drain(5000): os._exit(0)  # the same shutdown as gui/app.py
print("EXITED-CLEANLY", flush=True)
"""
    bad, waited = [], 0
    for i in range(10):
        r = _child(code)
        if r.returncode != 0:                        # 0xC0000409 / SIGABRT: Qt aborted the program
            tail = (r.stderr.strip().splitlines() or ["(no message)"])[-1]
            bad.append(f"exit {r.returncode}: {tail[:120]}")
        elif "EXITED-CLEANLY" in r.stdout:
            waited += 1
    if bad:
        return result("FAIL", f"{len(bad)} of 10 quits crashed. First: {bad[0]}",
                      "Keep every running _Worker referenced until it finishes; on quit, wait() for them "
                      "(or give each a parent and quit() + wait() in closeEvent).")
    return result("PASS", f"10 of 10 quits closed without a crash ({waited} after the running work finished, "
                  f"{10 - waited} by leaving after the 5 s wait)")


@probe("Q9b", "Panel (Qt)", "Quitting while a download is stuck (it would take 40 s)", timeout=90)
def quit_with_stuck_worker():
    code = r"""
from mygeeky.gui.qt_panel import _Worker
p = MyGeekyPanel(config_mod.MyGeekyConfig(github_username="probe-user")); p.show(); wait(0.3)
w = _Worker(lambda: time.sleep(40)); w.start(); w = None
p.close(); app.quit()
t0 = time.time()
if _Worker.drain(5000):
    print("LEFT-AFTER %.1f" % (time.time() - t0), flush=True); os._exit(0)
print("EXITED-CLEANLY", flush=True)
"""
    t0 = time.time()
    r = _child(code)
    took = time.time() - t0
    left = next((l for l in r.stdout.splitlines() if l.startswith(("LEFT-AFTER", "EXITED"))), "")
    if r.returncode == 0 and left:
        return result("PASS", f"closed without a crash in {took:.0f} s in total ({left.lower()}); "
                      "the stuck download was abandoned")
    return result("FAIL", f"exit {r.returncode} after {took:.0f} s: {left or r.stderr[-200:]}",
                  "On quit, wait a few seconds for running work, then leave without destroying running threads.")


@probe("Q10", "Panel (Qt)", "Avatar pictures built off the UI thread (QPixmap in a worker)", timeout=60)
def pixmap_thread():
    code = r"""
from PySide6.QtCore import qInstallMessageHandler
msgs = []
qInstallMessageHandler(lambda mode, ctx, m: msgs.append(m))
from PySide6.QtGui import QPixmap, QImage, QColor
from mygeeky.gui import qt_panel
img = QImage(64, 64, QImage.Format_ARGB32); img.fill(QColor("red"))
path = config_mod.AVATAR_CACHE_DIR; path.mkdir(parents=True, exist_ok=True)
import hashlib
url = "https://example.invalid/a.png"
img.save(str(path / (hashlib.sha1(f"{url}@32".encode()).hexdigest() + ".png")))
qt_panel.AVATAR_CACHE_DIR = path
got = []
loader = qt_panel.AvatarLoader()
for i in range(30):
    loader._memory.clear()
    loader.request(url, 32, lambda pm: got.append(pm.isNull()))
wait(3)
print("WARNINGS", [m for m in msgs if "pixmap" in m.lower() or "thread" in m.lower()][:3], flush=True)
print("LOADED", len(got), flush=True)
from mygeeky.gui.qt_panel import _Worker
if _Worker.drain(5000): os._exit(0)
"""
    import inspect
    src = (ROOT / "src/mygeeky/gui/qt_panel.py").read_text(encoding="utf-8")
    in_worker = "def fetch() -> QPixmap" in src
    try:
        r = _child(code)
        warn = next((l for l in r.stdout.splitlines() if l.startswith("WARNINGS")), "")
        crashed = r.returncode != 0
    except subprocess.TimeoutExpired:
        warn, crashed = "", True
    if crashed:
        return result("FAIL", "the avatar loader crashed the process.", "Build QImage in the worker; convert to QPixmap on the UI thread.")
    if in_worker:
        return result("WARN", f"no crash in 30 loads here ({warn or 'no Qt warnings'}), but the worker creates "
                      "QPixmap objects, which Qt documents as UI-thread-only: a rare, random crash on some "
                      "graphics drivers/platforms (the kind that leaves no Python error).",
                      "In fetch(): load and round the picture as QImage; turn it into a QPixmap in _finish() on the UI thread.")
    return result("PASS", "pictures are made on the UI thread")


@probe("P3", "Panel (Qt)", "A bug inside the panel (an error in a button or timer)", timeout=60)
def slot_error():
    code = r"""
from mygeeky import crashreport
crashreport.install(config_mod.LOG_DIR)
p = MyGeekyPanel(config_mod.MyGeekyConfig(github_username="probe-user")); p.show(); wait(0.3)
from PySide6.QtCore import QTimer
QTimer.singleShot(50, lambda: int("not a number"))
wait(1)
print("ALIVE", p.isVisible(), "REPORTS", len(list(config_mod.LOG_DIR.glob("crash-*.txt"))), flush=True)
p.close(); app.quit()
from mygeeky.gui.qt_panel import _Worker
if _Worker.drain(5000): os._exit(0)
"""
    r = _child(code)
    line = next((l for l in r.stdout.splitlines() if l.startswith("ALIVE")), "")
    if line == "ALIVE True REPORTS 1":
        return result("PASS", "the panel kept running; the error was saved as a crash report and offered for sending")
    return result("FAIL", f"exit {r.returncode}, {line or r.stderr[-200:]}")


@probe("P3b", "Panel (Qt)", "A hard crash (the process dies, no Python error)", timeout=60)
def hard_crash():
    code = ("import sys, platformdirs; d=sys.argv[1]; "
            "platformdirs.user_data_dir=lambda *a,**k: d+'/data'; platformdirs.user_config_dir=lambda *a,**k: d+'/config'; "
            "sys.path.insert(0, sys.argv[2]); from mygeeky import crashreport, config; "
            "crashreport.install(config.LOG_DIR); import faulthandler; faulthandler._sigsegv()")
    from mygeeky import config, crashreport
    tmp = str(config.DATA_DIR.parent)
    subprocess.run([sys.executable, "-c", code, tmp, str(ROOT / "src")], capture_output=True)
    crashreport.install(config.LOG_DIR)                   # the next start
    n = len(crashreport.pending(config.LOG_DIR))
    return result("PASS" if n == 1 else "FAIL", f"after a segfault, the next start found {n} report(s) to offer")


@probe("D6", "Panel (Qt)", "Starting myGeeKy while it's already running")
def second_launch():
    from mygeeky.gui import app as gui_app
    if not hasattr(gui_app, "_bring_running_panel_forward"):
        return result("WARN", "the second start exits silently: nothing happens on screen. Users click again, "
                      "or think it's broken, when the panel is just folded at the screen edge.",
                      "Signal the running panel to unfold and come to the front (QLocalServer / QLocalSocket).")
    name = f"mygeeky-probe-{os.getpid()}"         # never the name your real panel listens on
    code = r"""
from mygeeky.gui import app as gui_app
gui_app._instance_name = lambda: %r
p = MyGeekyPanel(config_mod.MyGeekyConfig(github_username="probe-user")); p.show(); wait(0.3)
p.fold(); wait(0.3)
calls = []
real_unfold = p.unfold
p.unfold = lambda: (calls.append(1), real_unfold())
gui_app._listen_for_second_start(p)
import subprocess
second = ("import sys; sys.path.insert(0, sys.argv[1]); from mygeeky.gui import app; "
          "app._instance_name = lambda: %r; app._bring_running_panel_forward()")
proc = subprocess.Popen([sys.executable, "-c", second, sys.argv[2]])
end = time.time() + 15
while time.time() < end and not calls: wait(0.1)
proc.wait(10)
print("UNFOLDED", bool(calls), flush=True)
from mygeeky.gui.qt_panel import _Worker
if _Worker.drain(5000): os._exit(0)
""" % (name, name)
    r = _child(code)
    if "UNFOLDED True" in r.stdout:
        return result("PASS", "a second start reached the running panel, which unfolded and came to the front")
    return result("FAIL", f"the running panel wasn't reached (exit {r.returncode}): {r.stdout[-150:]} {r.stderr[-200:]}")


# ----------------------------------------------------------------------------- scheduled run
@probe("S1", "Weekly run", "Weekly run installed for a Python inside a folder with spaces (Linux cron)")
def cron_spaces():
    from mygeeky import scheduler
    scheduler._python_and_module = lambda: ("/home/probe user/my apps/venv/bin/python", "mygeeky")
    line = scheduler.cron_line()
    py = "/home/probe user/my apps/venv/bin/python"
    if f"'{py}'" in line or f'"{py}"' in line:
        return result("PASS", line)
    return result("FAIL", f"the cron line is `{line}`: the path is unquoted, so cron runs '/home/probe' and the "
                  "weekly run silently never happens.", "shlex.quote() every path in the cron line; create the logs folder first.")


@probe("S2", "Weekly run", "The PC is asleep or off at the weekly time (Windows)", platforms="win32")
def missed_task():
    from mygeeky import scheduler, winproc
    # a real throwaway task, made exactly as `schedule install` makes it, then deleted (never your real one)
    scheduler.TASK_NAME = f"myGeeKyProbeTask-{os.getpid()}"
    made = winproc.run(scheduler.windows_command(), shell=True, capture_output=True, text=True)
    if made.returncode != 0:
        return result("SKIP", f"couldn't create a test task here: {(made.stderr or made.stdout).strip()[:120]}")
    try:
        if hasattr(scheduler, "catch_up_settings"):
            scheduler.catch_up_settings()
        q = winproc.run(["powershell", "-NoProfile", "-Command",
                         f"$s=(Get-ScheduledTask -TaskName '{scheduler.TASK_NAME}').Settings; "
                         "\"$($s.StartWhenAvailable) $($s.DisallowStartIfOnBatteries)\""],
                        capture_output=True, text=True).stdout.split()
    finally:
        winproc.run(f'schtasks /Delete /TN "{scheduler.TASK_NAME}" /F', shell=True, capture_output=True, text=True)
    if q == ["True", "False"]:
        return result("PASS", "a real task made the way myGeeKy makes it runs when missed and on battery "
                      "(the test task was deleted)")
    return result("WARN", f"the task runs when missed / on battery: {q}. Made with `schtasks /SC WEEKLY /ST 09:00` "
                  "and nothing else, a laptop that's closed (or on battery) at Monday 09:00 skips that week.",
                  "Create it with PowerShell's New-ScheduledTaskSettingsSet -StartWhenAvailable (or task XML).")


# ----------------------------------------------------------------------------- phone app (reads the code)
@probe("M1", "Phone app", "Phone sign-in on a stalled network (no answer from GitHub)")
def mobile_login_timeout():
    p = ROOT / "mobile/src/lib/github-login.ts"
    if not p.exists():
        return result("PASS", "no such file")
    src = p.read_text(encoding="utf-8")
    raw = [i + 1 for i, l in enumerate(src.splitlines()) if "await fetch(" in l]
    if raw:
        return result("FAIL", f"github-login.ts calls plain fetch() (lines {raw}) with no timeout: on a stalled "
                      "network the sign-in spinner turns forever.", "Use fetchT (net.ts) like the rest of the app.")
    return result("PASS", "sign-in requests have a timeout")


@probe("M3", "Phone app", "Token unreadable after reinstall / phone backup restore")
def mobile_securestore():
    p = ROOT / "mobile/src/lib/storage.ts"
    src = p.read_text(encoding="utf-8") if p.exists() else ""
    i = src.find("getItemAsync")
    if i < 0:
        return result("PASS", "no SecureStore read")
    window = src[max(0, i - 300): i + 200]
    if "try" in window and "catch" in window:
        return result("PASS", "a failed SecureStore read is caught")
    return result("FAIL", "getToken() doesn't catch a failed SecureStore read ('Could not decrypt'), which "
                  "happens after a reinstall or restoring a phone backup: the app can fail on start.",
                  "Wrap it in try/catch; on failure delete the item and treat it as signed out.")


@probe("M7", "Phone app", "Coming back to the app after hours in the background")
def mobile_resume():
    hits = [p for p in (ROOT / "mobile/src").rglob("*.ts*") if "AppState" in p.read_text(encoding="utf-8")]
    if hits:
        return result("PASS", f"refreshes on resume ({hits[0].name})")
    return result("WARN", "nothing listens for the app coming back to the front (AppState): it shows "
                  "hours-old data until the user pulls to refresh.", "Refresh stale sections on AppState 'active'.")


# ----------------------------------------------------------------------------- the live panel
@probe("R1", "Running panel", "Your running panel: CPU and memory while idle, over 30 s", platforms="win32", timeout=60)
def live_resources():
    try:
        import psutil
    except ImportError:
        return result("WARN", "psutil isn't installed: not measured")
    procs = [p for p in psutil.process_iter(["cmdline"]) if "mygeeky.gui.app" in " ".join(p.info["cmdline"] or [])
             or ("mygeeky" in " ".join(p.info["cmdline"] or []) and "gui" in (p.info["cmdline"] or []))]
    if not procs:
        return result("WARN", "no running panel found: not measured")
    p = procs[0]
    p.cpu_percent(None); time.sleep(30)
    cpu, rss = p.cpu_percent(None), p.memory_info().rss / 2**20
    status = "PASS" if cpu < 3 and rss < 600 else "WARN"
    return result(status, f"{cpu:.1f}% CPU (of one core) and {rss:.0f} MB memory while idle")


# ----------------------------------------------------------------------------- runner
def _run_one(name: str) -> dict:
    _isolate()
    try:
        return PROBES[name]["fn"]()
    except Exception as exc:
        import traceback
        return result("ERROR", f"the probe itself failed: {type(exc).__name__}: {exc}\n{traceback.format_exc()[-600:]}")


def run_all(selected: list[str] | None = None) -> list[dict]:
    rows = []
    for name, meta in PROBES.items():
        if selected and name not in selected and meta["id"] not in selected:
            continue
        t0 = time.time()
        if meta["platforms"] != "all" and not sys.platform.startswith(meta["platforms"]):
            res = result("SKIP", f"only on {meta['platforms']}")
        else:
            try:
                r = subprocess.run([sys.executable, str(Path(__file__)), "--one", name], capture_output=True,
                                   text=True, timeout=meta["timeout"], encoding="utf-8", errors="replace")
                line = next((l for l in reversed(r.stdout.splitlines()) if l.startswith("RESULT ")), "")
                res = json.loads(line[7:]) if line else result("ERROR", f"no result (exit {r.returncode}): {r.stderr[-400:]}")
            except subprocess.TimeoutExpired:
                res = result("FAIL", f"the probe didn't finish in {meta['timeout']} s: the code it exercises hangs.")
        res.update(id=meta["id"], area=meta["area"], title=meta["title"], seconds=round(time.time() - t0, 1))
        rows.append(res)
        print(f"[{res['status']:5}] {meta['id']:4} {meta['title']}", flush=True)
    return rows


def write_report(rows: list[dict], path: Path) -> None:
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from mygeeky import __version__ as version
    except Exception:
        version = "?"
    try:                                   # the exact code that was checked
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "src"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        version += f" (commit {head}{' + local changes not committed yet' if dirty else ''})" if head else ""
    except OSError:
        pass
    count = {s: sum(r["status"] == s for r in rows) for s in ("FAIL", "WARN", "PASS", "SKIP", "ERROR")}
    order = {"FAIL": 0, "ERROR": 1, "WARN": 2, "PASS": 3, "SKIP": 4}
    lines = [f"# myGeeKy stability report", "",
             f"myGeeKy {version} · {platform.platform()} · Python {platform.python_version()} · "
             f"{datetime.now():%Y-%m-%d %H:%M}", "",
             f"**{count['FAIL']} fail · {count['WARN']} warn · {count['PASS']} pass**"
             + (f" · {count['SKIP']} skipped (other OS)" if count["SKIP"] else "")
             + (f" · {count['ERROR']} probe errors" if count["ERROR"] else ""), "",
             "Generated by `python stability/probes.py` (see PROTOCOL.md). Every probe ran in its own process "
             "with a throwaway data folder.", "",
             "| | ID | What was tried | What happened | Fix |", "|---|---|---|---|---|"]
    icon = {"FAIL": "❌", "WARN": "⚠️", "PASS": "✅", "SKIP": "➖", "ERROR": "❓"}
    for r in sorted(rows, key=lambda r: (order[r["status"]], r["area"], r["id"])):
        cell = lambda s: (s or "").replace("|", "\\|").replace("\n", " ")   # noqa: E731
        lines.append(f"| {icon[r['status']]} | {r['id']} | **{r['area']}:** {cell(r['title'])} | "
                     f"{cell(r['observed'])} | {cell(r['fix'])} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (path.with_suffix(".json")).write_text(json.dumps(rows, indent=2), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--one":
        out = _run_one(sys.argv[2])
        print("RESULT " + json.dumps(out), flush=True)
        os._exit(0)
    rows = run_all(sys.argv[1:] or None)
    write_report(rows, HERE / "REPORT.md")
    print(f"\nReport: {HERE / 'REPORT.md'}")
