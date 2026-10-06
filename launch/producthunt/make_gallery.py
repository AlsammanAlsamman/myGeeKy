"""Rebuild the Product Hunt gallery (1270x760) from docs/screenshots.

    python launch/producthunt/make_gallery.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "docs" / "screenshots"
OUT = Path(__file__).parent
W, H = 1270, 760


def font(size, bold=False):
    for f in (["C:/Windows/Fonts/segoeuib.ttf"] if bold else []) + ["C:/Windows/Fonts/segoeui.ttf"]:
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default()


def background():
    im = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(im)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(18 + 20 * t), int(16 + 8 * t), int(40 + 30 * t), 255))
    return im


def wrap(d, text, f, maxw):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) > maxw and cur:
            lines.append(cur)
            cur = w
        else:
            cur = t
    return lines + [cur]


def slide(images, title, sub, new=False, box=(470, 700)):
    im = background()
    d = ImageDraw.Draw(im)
    x = W - 70
    for path in reversed(images):
        shot = Image.open(path).convert("RGBA")
        shot.thumbnail(box, Image.LANCZOS)
        x -= shot.width
        im.alpha_composite(shot, (x, (H - shot.height) // 2))
        x -= 24
    textw = x - 110
    y = 210
    if new:
        d.rounded_rectangle((80, y - 50, 160, y - 16), 17, fill=(255, 111, 216, 255))
        d.text((96, y - 49), "NEW", font=font(22, True), fill="white")
    for ln in wrap(d, title, font(46, True), textw):
        d.text((80, y), ln, font=font(46, True), fill="white")
        y += 60
    y += 20
    for ln in wrap(d, sub, font(26), textw):
        d.text((80, y), ln, font=font(26), fill=(190, 205, 235))
        y += 38
    return im


def hero():
    im = background()
    d = ImageDraw.Draw(im)
    pic = Image.open(SHOTS / "hero.png").convert("RGBA")
    pic.thumbnail((1150, 540), Image.LANCZOS)
    im.alpha_composite(pic, ((W - pic.width) // 2, 190))
    icon = Image.open(ROOT / "src/mygeeky/gui/assets/icon_128.png").convert("RGBA").resize((84, 84))
    im.alpha_composite(icon, (60, 45))
    d.text((165, 48), "myGeeKy", font=font(46, True), fill="white")
    d.text((167, 108), "Find GitHub people who share your research — and will follow you back.",
           font=font(24), fill=(200, 220, 255))
    return im


SLIDES = [
    ("hero", None),
    ("suggestions", ([SHOTS / "suggestions.png"], "People in your field who'll actually follow back",
                     "Built from your CV, repos, ORCID & Google Scholar papers. Ranked by real follow-back odds.")),
    ("signals", ([SHOTS / "signals.png"], "Signals: say hi without words",
                 "Wave, \"I learn from you\", \"let's collaborate\" or \"following your work\": one click each, "
                 "emoji only, carried by GitHub itself, so there's no server. A handshake when it's mutual. "
                 "(Example data.)", True)),
    ("installer", ([SHOTS / "setup-welcome.png"], "Next → Next → Finish",
                   "A one-click Windows installer sets up Python, your read-only token, private sync and "
                   "shortcuts. Uninstall it from Settings → Apps.", True, (640, 600))),
    ("live", ([SHOTS / "live.png", SHOTS / "hearts.png"], "A live glass panel on your screen edge",
              "Friends' activity and fresh suggestions. Folded, it's a small icon that now and then "
              "lets out a few floating hearts.", False, (330, 560))),
    ("repos", ([SHOTS / "repos.png"], "Repos you could genuinely improve",
               "Active projects in your field with starter issues and maintainers who merge outside PRs.")),
    ("market", ([SHOTS / "market.png"], "Your field's repos as a market board",
                "Momentum by stars gained, commits and PyPI downloads. See who's rising this week.")),
    ("model", ([SHOTS / "model.png"], "It learns who follows you back",
               "A model retrains on your own follow-backs, so suggestions get sharper every week.")),
]

if __name__ == "__main__":
    for i, (name, spec) in enumerate(SLIDES, 1):
        img = hero() if spec is None else slide(*spec)
        img.convert("RGB").save(OUT / f"gallery-{i}-{name}.png")
        print(f"gallery-{i}-{name}.png")
