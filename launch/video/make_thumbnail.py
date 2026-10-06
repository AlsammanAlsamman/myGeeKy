"""YouTube thumbnail (1280x720) and the README's clickable video image (with a play button).

    python launch/video/make_thumbnail.py
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).parent))
from make_video import ASSETS, SHOTS, PINK, VIOLET, TEXT, MUTED, background, font, img, paste, emoji  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def thumbnail(play_button: bool) -> Image.Image:
    im = background(3).convert("RGBA")
    paste(im, img(SHOTS / "suggestions.png"), (1500, 560), 820, radius=26)
    paste(im, img(ASSETS / "icon_256.png"), (200, 210), 230, shadow=False)
    d = ImageDraw.Draw(im)
    d.text((330, 130), "myGeeKy", font=font(120, bold=True), fill=TEXT)
    y = 380
    for line in ("Find your people", "on GitHub."):
        d.text((110, y), line, font=font(118, bold=True), fill=TEXT)
        y += 135
    pill_w = d.textlength("Install in 2 minutes", font=font(60, bold=True)) + 70
    d.rounded_rectangle((110, y + 40, 110 + pill_w, y + 140), 50, fill=PINK)
    d.text((145, y + 52), "Install in 2 minutes", font=font(60, bold=True), fill=(255, 255, 255))
    emoji(im, "👥🛠️📈👋", (115, y + 190), 80)
    if play_button:
        ring = Image.new("RGBA", im.size, (0, 0, 0, 0))
        rd = ImageDraw.Draw(ring)
        cx, cy, r = 1500, 560, 120
        rd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(0, 0, 0, 170))
        rd.polygon([(cx - 38, cy - 62), (cx - 38, cy + 62), (cx + 66, cy)], fill=(255, 255, 255, 240))
        im.alpha_composite(ring)
    return im.convert("RGB").resize((1280, 720), Image.LANCZOS)


if __name__ == "__main__":
    thumbnail(False).save(Path(__file__).parent / "youtube-thumbnail.png")
    thumbnail(True).save(ROOT / "docs" / "video-thumbnail.png")
    print("thumbnails written")
