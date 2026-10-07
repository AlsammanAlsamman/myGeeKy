"""Render the myGeeKy intro / installation video (1080p, ~2.5 min) with an
original synthesized soundtrack.

    pip install pillow numpy imageio-ffmpeg
    python launch/video/make_video.py            ->  launch/video/mygeeky-intro.mp4
    python launch/video/make_video.py --preview  ->  a few still frames only (fast)

Everything is drawn from the repo's own screenshots and icons, so the video
can be re-rendered whenever the app changes.
"""

from __future__ import annotations

import math
import random
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "docs" / "screenshots"
ASSETS = ROOT / "src" / "mygeeky" / "gui" / "assets"
OUT = Path(__file__).parent
W, H, FPS = 1920, 1080, 30

BG = (18, 18, 28)
TEXT = (240, 240, 245)
MUTED = (170, 172, 190)
PINK = (255, 111, 216)
VIOLET = (122, 92, 255)
CYAN = (127, 216, 255)
GREEN = (52, 211, 153)
AMBER = (255, 196, 87)
RED = (248, 113, 113)


# --------------------------------------------------------------------------- helpers
def font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    name = "consola.ttf" if mono else ("segoeuib.ttf" if bold else "segoeui.ttf")
    return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size)


EMOJI = ImageFont.truetype("C:/Windows/Fonts/seguiemj.ttf", 109)   # bitmap strikes: draw at 109, scale


def ease(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def fade(t: float, start: float, end: float, f: float = 0.6) -> float:
    """0 -> 1 over `f` s after start, 1 -> 0 over `f` s before end."""
    return ease((t - start) / f) * ease((end - t) / f)


_cache: dict[str, Image.Image] = {}


def img(path: Path) -> Image.Image:
    key = str(path)
    if key not in _cache:
        _cache[key] = Image.open(path).convert("RGBA")
    return _cache[key]


def background(t: float) -> Image.Image:
    """Dark gradient with two slowly drifting glows (pink, violet)."""
    base = Image.new("RGB", (W, H), BG)
    glow = Image.new("RGB", (W // 8, H // 8), (0, 0, 0))
    g = ImageDraw.Draw(glow)
    for cx, cy, r, col in ((0.78 + 0.05 * math.sin(t / 7), 0.15, 70, VIOLET),
                           (0.12, 0.35 + 0.05 * math.cos(t / 9), 55, PINK)):
        g.ellipse((cx * W / 8 - r, cy * H / 8 - r, cx * W / 8 + r, cy * H / 8 + r), fill=col)
    glow = glow.filter(ImageFilter.GaussianBlur(30)).resize((W, H), Image.BILINEAR)
    return Image.blend(base, glow, 0.22)


def text_center(im: Image.Image, txt: str, y: int, fnt, color, alpha: float = 1.0) -> None:
    if alpha <= 0:
        return
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    w = d.textlength(txt, font=fnt)
    d.text(((W - w) / 2, y), txt, font=fnt, fill=color + (int(255 * alpha),))
    im.alpha_composite(layer)


def text_at(im: Image.Image, txt: str, xy, fnt, color, alpha: float = 1.0) -> None:
    if alpha <= 0:
        return
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(xy, txt, font=fnt, fill=color + (int(255 * alpha),))
    im.alpha_composite(layer)


def gradient_text(im: Image.Image, txt: str, y: int, fnt, alpha: float = 1.0) -> None:
    if alpha <= 0:
        return
    d = ImageDraw.Draw(im)
    w = int(d.textlength(txt, font=fnt))
    h = fnt.size + 20
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((0, 0), txt, font=fnt, fill=int(255 * alpha))
    grad = Image.new("RGBA", (w, h))
    gd = ImageDraw.Draw(grad)
    for x in range(w):
        k = x / max(w - 1, 1)
        gd.line([(x, 0), (x, h)], fill=tuple(int(PINK[i] + (VIOLET[i] - PINK[i]) * k) for i in range(3)) + (255,))
    grad.putalpha(mask)
    im.alpha_composite(grad, (int((W - w) / 2), y))


def emoji(im: Image.Image, chars: str, xy, size: int, alpha: float = 1.0) -> None:
    if alpha <= 0:
        return
    chars = chars.replace(chr(0xFE0F), "")   # the emoji-style selector draws as an empty gap
    tmp = Image.new("RGBA", (int(EMOJI.size * 1.3) * len(chars), int(EMOJI.size * 1.3)), (0, 0, 0, 0))
    ImageDraw.Draw(tmp).text((0, 0), chars, font=EMOJI, embedded_color=True)
    tmp = tmp.crop(tmp.getbbox())
    k = size / EMOJI.size
    tmp = tmp.resize((max(1, int(tmp.width * k)), max(1, int(tmp.height * k))), Image.LANCZOS)
    if alpha < 1:
        tmp.putalpha(tmp.getchannel("A").point(lambda a: int(a * alpha)))
    im.alpha_composite(tmp, (int(xy[0]), int(xy[1])))


def paste(im: Image.Image, src: Image.Image, center, height: int, alpha: float = 1.0, radius: int = 0,
          shadow: bool = True) -> None:
    if alpha <= 0:
        return
    k = height / src.height
    pic = src.resize((int(src.width * k), height), Image.LANCZOS)
    if radius:
        m = Image.new("L", pic.size, 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, pic.width, pic.height), radius, fill=255)
        pic.putalpha(Image.fromarray(np.minimum(np.array(pic.getchannel("A")), np.array(m))))
    x, y = int(center[0] - pic.width / 2), int(center[1] - pic.height / 2)
    if shadow:
        sh = Image.new("RGBA", (pic.width + 120, pic.height + 120), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle((60, 75, pic.width + 60, pic.height + 75), max(radius, 12),
                                             fill=(0, 0, 0, int(150 * alpha)))
        im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(28)), (x - 60, y - 60))
    if alpha < 1:
        pic.putalpha(pic.getchannel("A").point(lambda a: int(a * alpha)))
    im.alpha_composite(pic, (x, y))


def heart(d: ImageDraw.ImageDraw, x: float, y: float, s: float, color) -> None:
    pts = []
    for i in range(40):
        a = math.tau * i / 40
        hx = 16 * math.sin(a) ** 3
        hy = -(13 * math.cos(a) - 5 * math.cos(2 * a) - 2 * math.cos(3 * a) - math.cos(4 * a))
        pts.append((x + hx * s / 32, y + hy * s / 32))
    d.polygon(pts, fill=color)


def hearts(im: Image.Image, t: float, origin, start: float, n: int = 7, rise: float = 330) -> None:
    rnd = random.Random(int(start * 100))
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for i in range(n):
        born = start + i * 0.35 + rnd.uniform(0, 0.2)
        life = rnd.uniform(2.6, 3.4)
        age = t - born
        if not 0 <= age <= life:
            continue
        k = age / life
        x = origin[0] + rnd.uniform(-30, 30) + rnd.choice((-1, 1)) * rnd.uniform(20, 70) * k \
            + math.sin(i + age * 4) * 10
        y = origin[1] - ease(k) * rise
        s = rnd.uniform(26, 40) * (1 - 0.6 * k)
        col = rnd.choice((PINK, (255, 143, 192), (255, 92, 138), (232, 111, 216)))
        heart(d, x, y, s, col + (int(230 * min(1, age / 0.25) * (1 - k) ** 1.3),))
    im.alpha_composite(layer.filter(ImageFilter.GaussianBlur(0.6)))


def caption(im: Image.Image, title: str, sub: str, alpha: float, y: int = 860) -> None:
    text_center(im, title, y, font(56, bold=True), TEXT, alpha)
    if sub:
        text_center(im, sub, y + 78, font(32), MUTED, alpha)


def section_title(im: Image.Image, t: float, number: str, title: str, sub: str) -> None:
    a = ease(t / 0.6) * ease((3.6 - t) / 0.5)
    text_center(im, number, 330, font(40, bold=True), PINK, a)
    gradient_text(im, title, 390, font(110, bold=True), a)
    text_center(im, sub, 560, font(38), MUTED, a)


# --------------------------------------------------------------------------- terminal
class Terminal:
    """A typed-out terminal session: [(at, kind, text)], kind in
    'cmd' (typed after a $ prompt), 'out' (printed), 'ask' (prompt + typed answer after '|')."""

    def __init__(self, script, title="Terminal", width=1500, height=700, cps=22):
        self.script, self.title, self.w, self.h, self.cps = script, title, width, height, cps

    def draw(self, im: Image.Image, t: float, center=(W // 2, 470), alpha: float = 1.0) -> None:
        if alpha <= 0:
            return
        layer = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        d.rounded_rectangle((0, 0, self.w, self.h), 22, fill=(13, 13, 20, 245), outline=(255, 255, 255, 40))
        d.rounded_rectangle((0, 0, self.w, 54), 22, fill=(32, 32, 46, 255))
        d.rectangle((0, 30, self.w, 54), fill=(32, 32, 46, 255))
        for i, c in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
            d.ellipse((24 + i * 34, 17, 44 + i * 34, 37), fill=c + (255,))
        tw = d.textlength(self.title, font=font(24))
        d.text(((self.w - tw) / 2, 12), self.title, font=font(24), fill=MUTED + (255,))
        mono = font(30, mono=True)
        lines: list[tuple[str, tuple]] = []
        for at, kind, txt in self.script:
            if t < at:
                break
            typed = int((t - at) * self.cps)
            if kind == "cmd":
                lines.append(("$ " + txt[:typed], CYAN))
            elif kind == "out":
                for ln in txt.split("\n"):
                    color = GREEN if ln.strip().startswith("✓") else (RED if ln.strip().startswith("✗") else TEXT)
                    lines.append((ln, color))
            elif kind == "ask":
                q, a = txt.split("|", 1)
                lines.append((q + a[:typed], TEXT))
        lines = lines[-int((self.h - 90) / 42):]
        sym = ImageFont.truetype("C:/Windows/Fonts/seguisym.ttf", 30)
        for i, (ln, col) in enumerate(lines):
            x, y = 34, 78 + i * 42
            for part_i, part in enumerate(ln.split("✓")):   # Consolas has no check mark
                if part_i:
                    d.text((x, y), "✓", font=sym, fill=GREEN + (255,))
                    x += d.textlength("✓", font=sym)
                d.text((x, y), part, font=mono, fill=col + (255,))
                x += d.textlength(part, font=mono)
        if lines and int(t * 2) % 2 == 0:
            last = lines[-1][0]
            x = 34 + d.textlength(last, font=mono)
            y = 78 + (len(lines) - 1) * 42
            d.rectangle((x + 4, y + 4, x + 20, y + 36), fill=TEXT + (200,))
        if alpha < 1:
            layer.putalpha(layer.getchannel("A").point(lambda a: int(a * alpha)))
        sh = Image.new("RGBA", (self.w + 120, self.h + 120), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle((60, 80, self.w + 60, self.h + 80), 22, fill=(0, 0, 0, int(160 * alpha)))
        x0, y0 = center[0] - self.w // 2, center[1] - self.h // 2
        im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(30)), (x0 - 60, y0 - 60))
        im.alpha_composite(layer, (x0, y0))


PIP = Terminal([
    (0.3, "cmd", "pip install mygeeky"),
    (1.6, "out", "Collecting mygeeky\n  Downloading mygeeky-0.4.2-py3-none-any.whl (635 kB)"),
    (2.6, "out", "Successfully installed mygeeky-0.4.2"),
], title="Any OS: one pip command", height=330)

INIT = Terminal([
    (0.3, "cmd", "mygeeky init"),
    (1.4, "ask", "Your GitHub username: |your-name"),
    (2.9, "ask", "CV: (p)ath to a .txt/.md/.pdf file, (t)ype, or (s)kip: |p"),
    (3.8, "ask", "Path to your CV file: |my_cv.pdf"),
    (5.0, "out", "Saved CV text (8,412 chars)"),
    (5.6, "ask", "ORCID iD: |0000-0002-1825-0097"),
    (7.2, "out", "Fetching your publications...\n  OpenAlex: 48 works, topics: GWAS, fine-mapping, genomics"),
    (8.8, "ask", "Topics/interests: |gwas, single-cell, bioinformatics"),
    (10.8, "ask", "Paste your GitHub token (input hidden): |********"),
    (12.0, "out", "Token stored securely in your OS keyring."),
    (13.0, "cmd", "mygeeky gui"),
    (14.2, "out", "Installing Qt for the myGeeKy panel (one time only)...\n✓ Qt is ready. The panel opens."),
], title="mygeeky init: tell it who you are")

BEACON = Terminal([
    (0.3, "cmd", "mygeeky beacon init"),
    (1.3, "out", "Step 1 of 3: your public beacon repo\n  1. Open github.com/new?name=mygeeky-beacon\n"
                 "  2. Check the owner, then click 'Create repository'"),
    (3.6, "out", "  ✓ your-name/mygeeky-beacon exists and is public."),
    (4.6, "out", "Step 2 of 3: a token that can write to that repo only\n"
                 "  Only select repositories -> mygeeky-beacon\n  Contents -> Read and write"),
    (7.0, "ask", "Paste the token (input hidden): |********"),
    (8.2, "out", "  ✓ The token works. It's stored in your OS keyring."),
    (9.0, "out", "Step 3 of 3: checking that others can see you\n  ✓ beacon.json is published"),
    (10.4, "out", "Your beacon is live. Signals are private: only the person you\n"
                  "  send one to can read it, and no reply is ever expected."),
], title="mygeeky beacon init: join Signals (optional)")


# --------------------------------------------------------------------------- scenes
def s_hook(t: float) -> Image.Image:
    """A crowd of dots: 100 million developers; a few in your field glow, then fade into the noise."""
    im = background(t).convert("RGBA")
    rnd = random.Random(7)
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    dense = ease(t / 3)
    for i in range(int(2600 * dense) + 120):
        x, y = rnd.uniform(0, W), rnd.uniform(0, H)
        x += math.sin(t * 0.7 + i) * 6
        special = i % 211 == 0
        if special and 4.5 < t < 11:
            glow = ease((t - 4.5) / 0.8) * (1 - ease((t - 9.2) / 1.6))
            r = 7 + 4 * glow
            d.ellipse((x - r * 3, y - r * 3, x + r * 3, y + r * 3), fill=PINK + (int(50 * glow),))
            d.ellipse((x - r, y - r, x + r, y + r), fill=PINK + (int(120 + 135 * glow),))
        else:
            r = rnd.uniform(1.8, 4.2)
            d.ellipse((x - r, y - r, x + r, y + r), fill=(170, 172, 205, int(rnd.uniform(70, 170))))
    im.alpha_composite(layer)
    band = Image.new("RGBA", im.size, (0, 0, 0, 0))   # a dark band behind the words only
    ImageDraw.Draw(band).rectangle((0, 400, W, 620), fill=BG + (205,))
    im.alpha_composite(band.filter(ImageFilter.GaussianBlur(40)))
    text_center(im, "GitHub has over 100 million developers.", 470, font(76, bold=True), TEXT, fade(t, 0.3, 4.4))
    text_center(im, "The few who share your research...", 470, font(76, bold=True), PINK, fade(t, 4.6, 8.4))
    text_center(im, "...are buried under accounts that will never notice you.", 470,
                font(66, bold=True), TEXT, fade(t, 8.6, 12.6))
    return im


def s_reveal(t: float) -> Image.Image:
    im = background(t + 12).convert("RGBA")
    k = ease(t / 1.4)
    size = int(150 + 130 * k)
    halo = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse((W / 2 - size, 380 - size, W / 2 + size, 380 + size), fill=PINK + (int(70 * k),))
    im.alpha_composite(halo.filter(ImageFilter.GaussianBlur(60)))
    hearts(im, t, (W / 2, 380 - size / 2.4), 0.9, n=9, rise=300)
    paste(im, img(ASSETS / "icon_256.png"), (W / 2, 380), size, alpha=k, shadow=False)
    text_center(im, "myGeeKy", 560, font(130, bold=True), TEXT, ease((t - 1.0) / 0.7))
    gradient_text(im, "the people, projects, papers and pulse of your field", 730, font(54, bold=True), ease((t - 1.8) / 0.7))
    text_center(im, "for developers and researchers on GitHub", 820, font(38), MUTED, ease((t - 2.6) / 0.7))
    return im


PILLARS = [
    ("👥", "People", "who share your research and will follow you back", CYAN),
    ("🛠️", "Projects", "repos in your field that welcome your pull requests", GREEN),
    ("📈", "Pulse", "what's rising in your field, every day", AMBER),
    ("🔬", "Research", "papers gaining citations fastest, and their code", GREEN),
    ("🗞️", "News", "arXiv, bioRxiv and Hacker News, for your topics", RED),
    ("📰", "Activity", "what your people are building right now", VIOLET),
    ("🙏", "Signals", "private thank-yous; no reply needed", PINK),
    ("🧠", "Learning", "learns what you're into, keeps room to explore", VIOLET),
    ("💡", "Ideas", "send ideas and problems straight to the maker", AMBER),
]


def s_pillars(t: float) -> Image.Image:
    im = background(t + 20).convert("RGBA")
    a = ease(t / 0.6) * ease((16 - t) / 0.6)
    text_center(im, "One profile. Your whole field.", 90, font(76, bold=True), TEXT, a)
    text_center(im, "from your CV, your repos, and your ORCID & Google Scholar papers", 195, font(36), MUTED, a)
    tw, th, gx, gy = 540, 200, 36, 28
    x0 = (W - (3 * tw + 2 * gx)) / 2
    for i, (em, name, line, col) in enumerate(PILLARS):
        appear = ease((t - 1.2 - i * 1.05) / 0.6) * a
        if appear <= 0:
            continue
        x = x0 + (i % 3) * (tw + gx)
        y = 330 + (i // 3) * (th + gy) + (1 - appear) * 40
        card = Image.new("RGBA", im.size, (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        cd.rounded_rectangle((x, y, x + tw, y + th), 26, fill=(255, 255, 255, int(16 * appear)),
                             outline=(255, 255, 255, int(45 * appear)))
        cd.rounded_rectangle((x + 30, y + 26, x + 90, y + 32), 4, fill=col + (int(255 * appear),))
        im.alpha_composite(card)
        emoji(im, em, (x + 30, y + 48), 46, appear)
        text_at(im, name, (x + 92, y + 48), font(44, bold=True), col, appear)
        words, lines, cur = line.split(), [], ""
        for wd in words:
            test = (cur + " " + wd).strip()
            if ImageDraw.Draw(im).textlength(test, font=font(29)) > tw - 60:
                lines.append(cur)
                cur = wd
            else:
                cur = test
        lines.append(cur)
        for j, ln in enumerate(lines):
            text_at(im, ln, (x + 30, y + 112 + j * 38), font(29), (225, 228, 240), appear)
    return im


def s_install(t: float) -> Image.Image:
    im = background(t + 40).convert("RGBA")
    if t < 3.6:
        section_title(im, t, "STEP 1", "Install", "one minute, no admin rights")
        return im
    t -= 3.6
    pages = ["setup-welcome.png", "setup-github.png", "setup-signals.png", "setup-finish.png"]
    labels = ["Download MyGeeKySetup.exe: it installs Python and Git if needed",
              "Token 1: checked to be truly read-only, kept in your keyring",
              "Signals: token 2 is checked to write to one repo only", "Start menu, startup, and you're done"]
    seg = 3.4
    for i, p in enumerate(pages):
        a = fade(t, i * seg, (i + 1) * seg + 0.4, 0.5)
        if a > 0:
            zoom = 1 + 0.03 * ((t - i * seg) / seg)
            paste(im, img(SHOTS / p), (W / 2, 470), int(720 * zoom), alpha=a, radius=18)
            caption(im, labels[i], "", a, y=890)
    text_center(im, "WINDOWS: Next  →  Next  →  Finish", 40, font(40, bold=True), PINK, fade(t, 0, 4 * seg + 0.4))
    if t > 4 * seg + 0.4:
        tt = t - (4 * seg + 0.4)
        PIP.draw(im, tt, center=(W // 2, 480), alpha=ease(tt / 0.5) * ease((5.6 - tt) / 0.5))
        caption(im, "macOS, Linux or Windows: one pip command", "the panel sets up its own GUI library the first time",
                ease(tt / 0.5) * ease((5.6 - tt) / 0.5), y=760)
    return im


def s_configure(t: float) -> Image.Image:
    im = background(t + 60).convert("RGBA")
    if t < 3.6:
        section_title(im, t, "STEP 2", "Configure", "a few answers, and it knows your field")
        return im
    t -= 3.6
    a = ease(t / 0.5) * ease((17.4 - t) / 0.5)
    INIT.draw(im, t, center=(W // 2, 470), alpha=a)
    caption(im, "Your CV and papers become your profile", "only your GitHub username is required", a, y=880)
    return im


def s_signals(t: float) -> Image.Image:
    im = background(t + 80).convert("RGBA")
    if t < 3.6:
        section_title(im, t, "STEP 3 · OPTIONAL", "Join Signals", "private thank-yous between myGeeKy users")
        emoji(im, "🙏📚👀🤝", (W / 2 - 230, 650), 100, ease(t / 0.6) * ease((3.6 - t) / 0.5))
        return im
    t -= 3.6
    a = ease(t / 0.5) * ease((12.6 - t) / 0.5)
    BEACON.draw(im, t, center=(W // 2, 470), alpha=a)
    caption(im, "It walks you through every step", "and checks each one worked", a, y=880)
    return im


TOUR = [
    ("suggestions.png", "People in your field who'll follow you back",
     "and the domain experts a follower count would bury"),
    ("repos.png", "Projects that welcome your pull requests", "starter issues, and maintainers who actually merge"),
    ("market.png", "The pulse of your field", "stars, commits and downloads: who's rising this week"),
    ("signals.png", "Say thanks, privately", "only they can read it, and no reply is expected"),
    ("activity.png", "What your people are building, live", "one card per person, right on your screen edge"),
    ("research.png", "The papers behind the code", "rising papers, their repos, and the people behind them"),
    ("news.png", "News from your field, not everyone's", "arXiv, bioRxiv and Hacker News, matched to you"),
    ("model.png", "See what myGeeKy knows about you", "your field, what you're into lately, and new territory"),
]


def s_tour(t: float) -> Image.Image:
    im = background(t + 100).convert("RGBA")
    if t < 3.6:
        section_title(im, t, "STEP 4", "Meet your panel", "always on top, on the edge of your screen")
        return im
    t -= 3.6
    seg = 5.0
    for i, (shot, title, sub) in enumerate(TOUR):
        a = fade(t, i * seg, (i + 1) * seg, 0.45)   # no overlap: captions sit where the next shot goes
        if a <= 0:
            continue
        k = (t - i * seg) / seg
        side = -1 if i % 2 == 0 else 1
        px = W / 2 + side * 420 + side * 20 * k
        paste(im, img(SHOTS / shot), (px, 540), int(800 * (1 + 0.04 * k)), alpha=a, radius=26)
        tx = 170 if side == 1 else W / 2 + 110
        lines, cur, words = [], "", title.split()
        for wd in words:
            test = (cur + " " + wd).strip()
            if ImageDraw.Draw(im).textlength(test, font=font(64, bold=True)) > 700:
                lines.append(cur)
                cur = wd
            else:
                cur = test
        lines.append(cur)
        for j, ln in enumerate(lines):
            text_at(im, ln, (tx, 400 + j * 80), font(64, bold=True), TEXT, a)
        y = 400 + len(lines) * 80 + 20
        if "👋" in sub:
            emoji(im, "👋📚🤝", (tx, y), 54, a)
            text_at(im, "(example data)", (tx, y + 80), font(32), MUTED, a)
        else:
            text_at(im, sub, (tx, y), font(34), MUTED, a)
    return im


def s_close(t: float) -> Image.Image:
    im = background(t + 140).convert("RGBA")
    a = ease(t / 0.8)
    hearts(im, t, (W / 2, 300), 0.4, n=10, rise=260)
    hearts(im, t, (W / 2, 300), 3.6, n=8, rise=260)
    paste(im, img(ASSETS / "icon_256.png"), (W / 2, 300), 230, alpha=a, shadow=False)
    gradient_text(im, "Your corner of GitHub.", 450, font(96, bold=True), ease((t - 0.6) / 0.7))
    text_center(im, "Free and open source. It only suggests; it never acts for you.", 600, font(38), MUTED,
                ease((t - 1.3) / 0.7))
    pill = Image.new("RGBA", im.size, (0, 0, 0, 0))
    pa = ease((t - 2.0) / 0.7)
    ImageDraw.Draw(pill).rounded_rectangle((W / 2 - 330, 700, W / 2 + 330, 790), 20,
                                           fill=(0, 0, 0, int(120 * pa)), outline=(255, 255, 255, int(50 * pa)))
    im.alpha_composite(pill)
    text_center(im, "pip install mygeeky", 718, font(46, mono=True), CYAN, pa)
    text_center(im, "mygeeky.org", 840, font(54, bold=True), TEXT, ease((t - 2.6) / 0.7))
    text_center(im, "github.com/AlsammanAlsamman/myGeeKy  ·  ideas welcome", 920, font(32), MUTED, ease((t - 3.0) / 0.7))
    return im


SCENES = [(s_hook, 13.0), (s_reveal, 6.0), (s_pillars, 16.5), (s_install, 23.6), (s_configure, 21.0),
          (s_signals, 16.2), (s_tour, 44.0), (s_close, 8.0)]


def frame_at(t: float) -> Image.Image:
    start = 0.0
    for scene, dur in SCENES:
        if t < start + dur:
            im = scene(t - start)
            break
        start += dur
    else:
        im = s_close(SCENES[-1][1])
    total = sum(d for _, d in SCENES)
    if t > total - 1.2:   # fade to black at the very end
        im.alpha_composite(Image.new("RGBA", im.size, (0, 0, 0, int(255 * ease((t - total + 1.2) / 1.2)))))
    return im.convert("RGB")


# --------------------------------------------------------------------------- soundtrack
def soundtrack(path: Path, seconds: float, sr: int = 44100) -> None:
    """Original ambient score: a low drone, slow pad chords (Am-F-C-G), a soft
    arpeggio that enters after the reveal, a riser into the logo, and a swell at the end."""
    n = int(seconds * sr)
    t = np.arange(n) / sr
    out = np.zeros(n)

    def note(f):
        return 440.0 * 2 ** ((f - 69) / 12)

    def env(start, dur, attack=1.5, release=2.0):
        e = np.clip((t - start) / attack, 0, 1) * np.clip((start + dur - t) / release, 0, 1)
        return e * ((t >= start) & (t <= start + dur))

    out += 0.10 * np.sin(2 * np.pi * note(33) * t) * np.clip(t / 4, 0, 1)            # A1 drone
    chords = [(57, 60, 64), (53, 57, 60), (48, 52, 55), (55, 59, 62)]                 # Am F C G
    bar = 4.0
    for b in range(int(seconds / bar) + 1):
        start = b * bar
        for m in chords[b % 4]:
            f = note(m)
            e = env(start, bar + 1.5, attack=1.2, release=1.8)
            out += 0.035 * e * (np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * f * 1.003 * t)
                                + 0.25 * np.sin(2 * np.pi * f * 2 * t))
    arp_start = 19.0
    step = 0.25
    for k in range(int((seconds - arp_start - 6) / step)):
        start = arp_start + k * step
        b = int(start / bar) % 4
        m = chords[b][k % 3] + 12 + (12 if k % 8 >= 6 else 0)
        f = note(m)
        idx = (t >= start) & (t < start + 1.2)
        tt = t[idx] - start
        out[idx] += 0.028 * np.sin(2 * np.pi * f * tt) * np.exp(-tt * 4.5)
    riser = (t > 9) & (t < 13)
    out[riser] += 0.05 * np.sin(2 * np.pi * (200 + (t[riser] - 9) ** 2 * 60) * t[riser]) * ((t[riser] - 9) / 4) ** 2
    hit = (t >= 13) & (t < 17)
    out[hit] += 0.18 * np.sin(2 * np.pi * note(45) * t[hit]) * np.exp(-(t[hit] - 13) * 1.5)
    # a light "reverb": a few decaying echoes
    wet = np.zeros(n)
    for delay, g in ((0.12, 0.35), (0.23, 0.25), (0.41, 0.15)):
        d = int(delay * sr)
        wet[d:] += g * out[:-d]
    out = out + wet
    out *= np.clip((seconds - t) / 2.5, 0, 1)                                         # fade out
    out /= max(1e-9, np.abs(out).max()) / 0.8
    stereo = np.stack([out, np.roll(out, int(0.012 * sr))], axis=1)
    data = (stereo * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(data.tobytes())


# --------------------------------------------------------------------------- render
def main() -> None:
    import imageio_ffmpeg
    total = sum(d for _, d in SCENES)
    if "--preview" in sys.argv:
        for sec in (2, 6, 10, 16, 30, 44, 56, 72, 92, 104, 122, 134):
            frame_at(sec).save(OUT / f"preview_{sec:03d}.png")
        print("preview frames written")
        return
    audio = OUT / "soundtrack.wav"
    soundtrack(audio, total)
    video = OUT / "mygeeky-intro.mp4"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    proc = subprocess.Popen([
        ffmpeg, "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-i", str(audio),
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(video)],
        stdin=subprocess.PIPE)
    frames = int(total * FPS)
    for i in range(frames):
        proc.stdin.write(frame_at(i / FPS).tobytes())
        if i % (FPS * 10) == 0:
            print(f"  {i / FPS:5.0f}s / {total:.0f}s", flush=True)
    proc.stdin.close()
    proc.wait()
    frame_at(total * 0.18).save(OUT / "thumbnail.png")
    print(f"Wrote {video} ({video.stat().st_size / 1e6:.1f} MB, {total:.0f} s)")


if __name__ == "__main__":
    main()
