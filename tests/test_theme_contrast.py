"""Every theme names a colour for every kind of text, and each one is readable
on that theme's own background (WCAG contrast 4.5:1 for normal text)."""

import pytest

from mygeeky.gui.app import THEMES

ROLES = ("text", "muted", "title", "link", "good", "bad", "warn", "cat_ai", "cat_science", "cat_tech", "explore")
# what text actually sits on: the panel colour under the card tint
BACKGROUNDS = {"midnight": (28, 28, 42), "frosted": (255, 255, 255), "aurora": (39, 36, 99)}


def _rgb(spec: str, under: tuple[int, int, int]) -> tuple[float, float, float]:
    spec = spec.strip()
    if spec.startswith("#"):
        h = spec[1:]
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    nums = [float(x) for x in spec[spec.index("(") + 1:spec.index(")")].split(",")]
    a = nums[3] / 255 if len(nums) == 4 and nums[3] > 1 else (nums[3] if len(nums) == 4 else 1)
    return tuple(nums[i] * a + under[i] * (1 - a) for i in range(3))     # blended over the background


def _lum(c) -> float:
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@pytest.mark.parametrize("name", list(THEMES))
def test_every_text_role_is_defined_and_readable(name):
    theme, bg = THEMES[name], BACKGROUNDS[name]
    missing = [r for r in ROLES if r not in theme]
    assert not missing, f"{name} has no colour for {missing}"
    weak = {r: round(contrast(_rgb(theme[r], bg), bg), 2) for r in ROLES if contrast(_rgb(theme[r], bg), bg) < 4.5}
    assert not weak, f"{name}: too faint to read on its background: {weak}"


def test_switching_theme_restyles_the_market_buttons(monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from mygeeky.config import MyGeekyConfig
    from mygeeky.gui import app as logic
    from mygeeky.gui.qt_panel import MyGeekyPanel
    monkeypatch.setattr(logic, "set_theme", lambda cfg, name: setattr(cfg, "gui_theme", name) or True)
    panel = MyGeekyPanel(MyGeekyConfig(github_username="me", gui_theme="frosted"))
    try:
        panel._set_market_mode("repos")
        assert THEMES["frosted"]["text"] in panel.market_mode_buttons["repos"].styleSheet()
        panel._on_theme_clicked("midnight")
        style = panel.market_mode_buttons["repos"].styleSheet()
        assert THEMES["midnight"]["text"] in style and THEMES["frosted"]["text"] not in style
    finally:
        panel.ticker.stop()
        for t in (panel._activity_timer, panel._signals_timer, panel._update_timer, panel._news_timer,
                  panel._dock_guard, panel._sync_timer):
            t.stop()
        for w in list(panel._workers):
            w.wait(3000)
        panel.close()
        panel.deleteLater()
