"""Re-render every screenshot in docs/screenshots from the real panel.

    python docs/make_screenshots.py

Uses your own config and cached data (People, Repos, Market, Research, News,
Activity, Model). Signals uses made-up example people, since it shows other
users. Banners (update, token expiry) are switched off so the shots are clean.
Also writes docs/screenshots/hero.png (three tabs side by side) and
docs/tour.gif (every tab, crossfading) for the README.
"""

from __future__ import annotations

import dataclasses
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("QT_SCALE_FACTOR", "2")
ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "docs" / "screenshots"

TABS = [  # (file, tab, market mode)
    ("live", "live", None), ("suggestions", "suggestions", None), ("repos", "repos", None),
    ("market", "market", "repos"), ("research", "market", "research"), ("news", "news", None),
    ("activity", "activity", None), ("signals", "signals", None), ("model", "model", None),
]


SHOW_EXAMPLES = {"on": False}   # only the Signals tab shows example people, never Live


def example_signals(cfg, force=False):
    if not SHOW_EXAMPLES["on"]:
        return {"enabled": True, "can_send": True, "incoming": [], "people": [], "fetched_at": None, "error": None}
    now = datetime.now(timezone.utc)
    ago = lambda h: (now - timedelta(hours=h)).isoformat()  # noqa: E731
    people = [("ada-genomics", "🔬 deep in analysis", ["gwas", "fine mapping", "python"]),
              ("lin-spatial", "☕ open to chat", ["single cell", "spatial transcriptomics"]),
              ("omar-plants", "🌱 learning", ["plant genomics", "population genetics", "r"])]
    return {
        "enabled": True, "can_send": True, "fetched_at": ago(0.1), "error": None,
        "incoming": [
            {"from": "ada-genomics", "avatar_url": "", "profile_url": "", "type": "thanks", "emoji": "🙏",
             "text": "🙏 thanked you for your work", "repo": "", "at": ago(1), "mutual": False},
            {"from": "lin-spatial", "avatar_url": "", "profile_url": "", "type": "collab", "emoji": "🤝",
             "text": "🤝 you both want to collaborate", "repo": "", "at": ago(5), "mutual": True},
            {"from": "omar-plants", "avatar_url": "", "profile_url": "", "type": "used", "emoji": "⭐",
             "text": "⭐ used your-name/finemap-kit in their work", "repo": "", "at": ago(26), "mutual": False},
        ],
        "people": [{"login": p, "avatar_url": "", "profile_url": "", "status": s, "interests": i, "shared": i[:2],
                    "signalled_you": True, "you_signalled": p == "ada-genomics", "can_receive": True} for p, s, i in people],
    }


def render() -> dict[str, Path]:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from mygeeky.config import load_config
    from mygeeky.gui import app as logic
    logic.get_update_info = lambda cfg: {"show": False}
    logic.get_token_warnings = lambda cfg: []
    logic.save_config = lambda c: None
    logic.get_signals = example_signals
    logic.is_admin = lambda cfg: False      # the maker's private tab stays out of public pictures
    for name in ("news_refresh_due", "trends_due", "market_refresh_due"):
        setattr(logic, name, lambda cfg: False)
    from mygeeky.gui.qt_panel import MyGeekyPanel

    def pump(seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            time.sleep(0.03)

    cfg = dataclasses.replace(load_config(), gui_hearts_enabled=False, gui_panel_height_fraction=0.62)
    panel = MyGeekyPanel(cfg)
    panel.setAttribute(Qt.WA_DontShowOnScreen, True)
    panel.show()
    pump(3)
    out = {}
    for fname, tab, mode in TABS:
        if tab == "signals":
            SHOW_EXAMPLES["on"] = True
            panel._refresh_signals(force=True)
        panel._switch_tab(tab)
        if mode:
            panel._set_market_mode(mode)
        pump(2.5)
        path = SHOTS / f"{fname}.png"
        panel.panel_frame.grab().save(str(path))
        out[fname] = path
        print("  ", path.name)
    return out


def setup_pages() -> None:
    """The installer's pages (welcome, token 1, Signals, finish), with your real state."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    from mygeeky import __version__, setup_api
    from mygeeky.gui import setup_wizard as sw
    # same answers the installer would get, computed in this process (no helper processes, no installs)
    sw.api = lambda python, action, payload=None, timeout=None, **kw: setup_api.ACTIONS[action](payload or {})
    sw.SetupWizard.detect = lambda self: self.info.update(version=__version__, editable=False) or self.info
    wiz = sw.SetupWizard()
    wiz.python = sys.executable
    wiz.refresh_state()
    welcome = wiz.page(0)                 # its background check dies when rendered off-screen; say it directly
    welcome._checked = True
    welcome.found.setText(f"Found myGeeKy {__version__}. Setup will update it and keep all your settings.")
    wiz.setAttribute(Qt.WA_DontShowOnScreen, True)
    wiz.show()
    for name, page_id, wait in (("setup-welcome", 0, 2), ("setup-github", 3, 2), ("setup-signals", 5, 8),
                                ("setup-finish", 6, 2)):
        wiz.setStartId(page_id)
        wiz.restart()
        end = time.time() + wait
        while time.time() < end:
            app.processEvents()
            time.sleep(0.03)
        wiz.grab().save(str(SHOTS / f"{name}.png"))
        print("  ", f"{name}.png")


def hero(shots: dict[str, Path]) -> None:
    from PIL import Image, ImageDraw, ImageFilter
    picks = [Image.open(shots[k]).convert("RGBA") for k in ("suggestions", "model", "research")]
    h = 1100
    picks = [p.resize((round(p.width * h / p.height), h), Image.LANCZOS) for p in picks]
    gap, pad = 60, 90
    W = sum(p.width for p in picks) + gap * (len(picks) - 1) + pad * 2
    H = h + pad * 2
    bg = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(bg)
    for y in range(H):   # deep violet -> midnight
        k = y / H
        d.line([(0, y), (W, y)], fill=(int(40 - 22 * k), int(22 - 4 * k), int(70 - 38 * k), 255))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for cx, color in ((0.2, (255, 111, 216, 90)), (0.8, (127, 216, 255, 80))):
        gd.ellipse([W * cx - 500, H * 0.5 - 420, W * cx + 500, H * 0.5 + 420], fill=color)
    bg.alpha_composite(glow.filter(ImageFilter.GaussianBlur(160)))
    x = pad
    for i, p in enumerate(picks):
        y = pad + (0 if i == 1 else 40)
        shadow = Image.new("RGBA", (p.width + 80, p.height + 80), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle([40, 40, p.width + 40, p.height + 40], 40, fill=(0, 0, 0, 150))
        bg.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(26)), (x - 40, y - 20))
        bg.alpha_composite(p, (x, y))
        x += p.width + gap
    bg.convert("RGB").save(SHOTS / "hero.png", optimize=True)
    print("   hero.png")


def tour(shots: dict[str, Path]) -> None:
    """Every tab, crossfading -- small enough for GitHub and PyPI."""
    from PIL import Image
    order = ["live", "suggestions", "repos", "market", "research", "news", "activity", "signals", "model"]
    w = 400
    frames_src = []
    for k in order:
        im = Image.open(shots[k]).convert("RGB")
        frames_src.append(im.resize((w, round(im.height * w / im.width)), Image.LANCZOS))
    h = max(f.height for f in frames_src)
    canvas = lambda f: (lambda c: (c.paste(f, (0, 0)), c)[1])(Image.new("RGB", (w, h), (18, 18, 28)))  # noqa: E731
    frames_src = [canvas(f) for f in frames_src]
    frames, durations = [], []
    for i, f in enumerate(frames_src):
        nxt = frames_src[(i + 1) % len(frames_src)]
        frames.append(f)
        durations.append(2200)
        for s in (0.25, 0.5, 0.75):
            frames.append(Image.blend(f, nxt, s))
            durations.append(70)
    pal = [f.quantize(colors=200, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for f in frames]
    pal[0].save(ROOT / "docs" / "tour.gif", save_all=True, append_images=pal[1:], duration=durations, loop=0,
                optimize=True, disposal=1)
    print("   tour.gif", round((ROOT / "docs" / "tour.gif").stat().st_size / 1e6, 1), "MB")


if __name__ == "__main__":
    shots = render()
    setup_pages()
    hero(shots)
    tour(shots)
    sys.stdout.flush()
    os._exit(0)   # skip Qt's slow teardown of background workers
