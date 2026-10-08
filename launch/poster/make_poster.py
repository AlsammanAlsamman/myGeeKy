"""The myGeeKy wall poster: A3 portrait at 300 dpi (prints sharp at A2 too).

    python launch/poster/make_poster.py   ->  launch/poster/mygeeky-poster.png and .pdf

Drawn from the repo's own screenshots and icon, so it can be re-made whenever
the app changes (run docs/make_screenshots.py first for fresh screenshots).
The QR code points at the GitHub page: it opens everywhere, including networks
that block young domains.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "docs" / "screenshots"
OUT = Path(__file__).parent
W, H = 3508, 4961                      # A3 at 300 dpi
QR_URL = "https://github.com/AlsammanAlsamman/myGeeKy"

TEXT = (244, 244, 250)
MUTED = (182, 184, 204)
PINK, VIOLET, CYAN = (255, 111, 216), (122, 92, 255), (127, 216, 255)
GREEN, AMBER = (52, 211, 153), (255, 196, 87)


def font(size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
    name = {"regular": "segoeui.ttf", "bold": "segoeuib.ttf", "semi": "seguisb.ttf", "black": "seguibl.ttf",
            "light": "segoeuil.ttf", "mono": "consola.ttf"}[weight]
    try:
        return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size)
    except OSError:
        return ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", size)


EMOJI = ImageFont.truetype("C:/Windows/Fonts/seguiemj.ttf", 109)


def emoji(im: Image.Image, chars: str, xy, size: int) -> None:
    tmp = Image.new("RGBA", (int(EMOJI.size * 1.4) * len(chars), int(EMOJI.size * 1.4)), (0, 0, 0, 0))
    ImageDraw.Draw(tmp).text((0, 0), chars.replace(chr(0xFE0F), ""), font=EMOJI, embedded_color=True)
    tmp = tmp.crop(tmp.getbbox())
    k = size / tmp.height
    tmp = tmp.resize((int(tmp.width * k), int(tmp.height * k)), Image.LANCZOS)
    im.alpha_composite(tmp, (int(xy[0]), int(xy[1])))


def gradient_text(im: Image.Image, text: str, xy, fnt, colors=(PINK, VIOLET, CYAN), center=False) -> int:
    d = ImageDraw.Draw(im)
    l, t, r, b = d.textbbox((0, 0), text, font=fnt)
    w, h = r - l, b - t
    x = xy[0] - w // 2 if center else xy[0]
    mask = Image.new("L", (w + 20, h + 40), 0)
    ImageDraw.Draw(mask).text((-l + 10, -t + 10), text, font=fnt, fill=255)
    grad = Image.new("RGBA", mask.size)
    gd = ImageDraw.Draw(grad)
    for i in range(mask.width):
        k = i / max(mask.width - 1, 1)
        if k < 0.5:
            c = [int(colors[0][j] + (colors[1][j] - colors[0][j]) * k * 2) for j in range(3)]
        else:
            c = [int(colors[1][j] + (colors[2][j] - colors[1][j]) * (k - 0.5) * 2) for j in range(3)]
        gd.line([(i, 0), (i, mask.height)], fill=(*c, 255))
    grad.putalpha(mask)
    im.alpha_composite(grad, (int(x - 10), int(xy[1] - 10)))
    return h


def text(im, s, xy, fnt, fill=TEXT, center=False, anchor_w=None):
    d = ImageDraw.Draw(im)
    if center:
        l, _, r, _ = d.textbbox((0, 0), s, font=fnt)
        xy = (xy[0] - (r - l) // 2 - l, xy[1])
    d.text(xy, s, font=fnt, fill=fill)


def wrap(s: str, fnt, width: int) -> list[str]:
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    lines, cur = [], ""
    for word in s.split():
        test = (cur + " " + word).strip()
        if d.textlength(test, font=fnt) > width and cur:
            lines.append(cur)
            cur = word
        else:
            cur = test
    return lines + [cur]


def background() -> Image.Image:
    bg = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(bg)
    for y in range(H):
        k = y / H
        d.line([(0, y), (W, y)], fill=(int(34 - 20 * k), int(20 - 6 * k), int(64 - 38 * k), 255))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    for (cx, cy, r, col) in ((0.15, 0.10, 1300, (*PINK, 95)), (0.92, 0.18, 1200, (*VIOLET, 110)),
                             (0.80, 0.58, 1300, (*CYAN, 60)), (0.10, 0.70, 1100, (*VIOLET, 70))):
        g.ellipse([W * cx - r, H * cy - r, W * cx + r, H * cy + r], fill=col)
    bg.alpha_composite(glow.filter(ImageFilter.GaussianBlur(320)))
    stars = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    s = ImageDraw.Draw(stars)
    rnd = random.Random(7)
    for _ in range(420):
        x, y, r = rnd.uniform(0, W), rnd.uniform(0, H), rnd.uniform(1.2, 4.2)
        s.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, rnd.randint(40, 150)))
    bg.alpha_composite(stars)
    return bg


def shot(im: Image.Image, path: Path, center, height: int, angle: float = 0.0) -> None:
    src = Image.open(path).convert("RGBA")
    k = height / src.height
    src = src.resize((int(src.width * k), height), Image.LANCZOS)
    mask = Image.new("L", src.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, src.width - 1, src.height - 1], 54, fill=255)
    src.putalpha(mask)
    pad = 160
    layer = Image.new("RGBA", (src.width + pad * 2, src.height + pad * 2), (0, 0, 0, 0))
    sh = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([pad, pad + 40, pad + src.width, pad + src.height + 40], 60,
                                         fill=(0, 0, 0, 170))
    layer.alpha_composite(sh.filter(ImageFilter.GaussianBlur(50)))
    layer.alpha_composite(src, (pad, pad))
    if angle:
        layer = layer.rotate(angle, resample=Image.BICUBIC, expand=True)
    im.alpha_composite(layer, (int(center[0] - layer.width / 2), int(center[1] - layer.height / 2)))


def card(im, box, radius=56, fill=(255, 255, 255, 18), outline=(255, 255, 255, 46)):
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(box, radius, fill=fill, outline=outline, width=4)
    im.alpha_composite(layer)


def qr(url: str, size: int) -> Image.Image:
    q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=20, border=2)
    q.add_data(url)
    q.make(fit=True)
    img = q.make_image(fill_color="#12121c", back_color="white").convert("RGBA")
    return img.resize((size, size), Image.NEAREST)


FEATURES = [
    ("📰", "Headlines for your field", "AI labs, journals and the tech press, ranked by what you work on", PINK),
    ("🔬", "Research that's rising", "papers gaining citations fastest, with their code", GREEN),
    ("🤗", "Models in your field", "trending on Hugging Face, in your field and everywhere", AMBER),
    ("👥", "Your people on GitHub", "researchers who share your work and will follow back", CYAN),
    ("🛠️", "Projects that want you", "repos in your field with starter issues", VIOLET),
    ("🔤", "Keywords with meaning", "add \u201cAI\u201d and it also finds LLMs and deep learning", PINK),
]


def main() -> None:
    im = background()
    M = 230                                  # side margin

    # ---- header
    icon = Image.open(ROOT / "src/mygeeky/gui/assets/icon.png").convert("RGBA").resize((470, 470), Image.LANCZOS)
    glow = Image.new("RGBA", (900, 900), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([150, 150, 750, 750], fill=(*PINK, 120))
    im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(90)), (W // 2 - 450, 10))
    im.alpha_composite(icon, (W // 2 - 235, 225))
    y = 740
    gradient_text(im, "myGeeKy", (W // 2, y), font(330, "black"), center=True)
    y += 470
    text(im, "What's new in your field?", (W // 2, y), font(178, "bold"), center=True)
    y += 225
    gradient_text(im, "Come and see. It's all here.", (W // 2, y), font(150, "bold"), center=True)
    y += 245
    for line in wrap("Research, AI news, models and the people in your field, picked for your own work, in "
                     "one small panel on your screen.", font(84), W - 2 * M - 300):
        text(im, line, (W // 2, y), font(84), MUTED, center=True)
        y += 112

    # ---- the panel, three views
    y_shots = y + 730
    shot(im, SHOTS / "models.png", (W * 0.215, y_shots + 60), 1240, angle=6)
    shot(im, SHOTS / "research.png", (W * 0.785, y_shots + 60), 1240, angle=-6)
    shot(im, SHOTS / "news.png", (W * 0.5, y_shots), 1440)

    # ---- what you get, every day
    y = y_shots + 770
    cols, gap = 3, 50
    cw = (W - 2 * M - gap * (cols - 1)) // cols
    ch = 300
    for i, (em, title, sub, col) in enumerate(FEATURES):
        cx = M + (i % cols) * (cw + gap)
        cy = y + (i // cols) * (ch + 40)
        card(im, [cx, cy, cx + cw, cy + ch], radius=48)
        ImageDraw.Draw(im).rounded_rectangle([cx + 50, cy + 46, cx + 150, cy + 58], 6, fill=(*col, 255))
        emoji(im, em, (cx + cw - 160, cy + 36), 100)
        tl = wrap(title, font(62, "bold"), cw - 230)[:2]
        for j, line in enumerate(tl):
            text(im, line, (cx + 50, cy + 84 + j * 74), font(62, "bold"), TEXT)
        sy = cy + 84 + len(tl) * 74 + 14
        for j, line in enumerate(wrap(sub, font(46), cw - 100)[:4 - len(tl)]):
            text(im, line, (cx + 50, sy + j * 58), font(46), MUTED)
    y += 2 * (ch + 40) + 20

    # ---- get it
    band_top = y
    card(im, [M, band_top, W - M, H - 200], radius=70, fill=(255, 255, 255, 26), outline=(255, 255, 255, 70))
    q = qr(QR_URL, 470)
    frame = Image.new("RGBA", (q.width + 60, q.height + 60), (255, 255, 255, 255))
    fm = Image.new("L", frame.size, 0)
    ImageDraw.Draw(fm).rounded_rectangle([0, 0, frame.width - 1, frame.height - 1], 40, fill=255)
    frame.putalpha(fm)
    frame.alpha_composite(q, (30, 30))
    qx, qy = W - M - 110 - frame.width, band_top + (H - 200 - band_top - frame.height) // 2
    im.alpha_composite(frame, (qx, qy))
    tx = M + 110
    ty = band_top + 70
    gradient_text(im, "Scan me to get it", (tx, ty), font(112, "black"))
    ty += 165
    text(im, "Free and open source.", (tx, ty), font(60, "semi"), TEXT)
    ty += 100
    for label, value in (("Windows", "the installer: Next \u2192 Next \u2192 Finish"),
                         ("Anywhere", "pip install mygeeky"),
                         ("Website", "mygeeky.org")):
        text(im, label, (tx, ty), font(52, "bold"), CYAN)
        text(im, value, (tx + 290, ty), font(52, "mono" if value.startswith("pip") else "regular"), TEXT)
        ty += 78

    text(im, "It only suggests. It never follows, stars or posts for you.   \u00b7   github.com/AlsammanAlsamman/myGeeKy",
         (W // 2, H - 150), font(50, "semi"), MUTED, center=True)

    rgb = im.convert("RGB")
    for name in ("mygeeky-poster", "mygeeky-poster-v2"):     # the first may be open in a viewer
        try:
            rgb.save(OUT / f"{name}.png", dpi=(300, 300), optimize=True)
            rgb.save(OUT / f"{name}.pdf", resolution=300)
            break
        except OSError:
            continue
    try:
        rgb.resize((W // 4, H // 4), Image.LANCZOS).save(OUT / "mygeeky-poster-preview.png")
    except OSError:
        pass                                                   # open in a viewer: keep the old preview
    print("wrote", OUT / "mygeeky-poster.png", "and .pdf")


if __name__ == "__main__":
    main()
