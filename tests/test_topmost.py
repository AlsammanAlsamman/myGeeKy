import sys

import pytest

from mygeeky.gui import topmost


class FakeUser32:
    def __init__(self, topmost_flag: bool):
        self.flag = topmost_flag
        self.lifted = []

    def GetWindowLongPtrW(self, hwnd, idx):  # noqa: N802
        return topmost.WS_EX_TOPMOST if self.flag else 0

    def SetWindowPos(self, hwnd, after, x, y, w, h, flags):  # noqa: N802
        self.lifted.append((after, flags))


@pytest.mark.parametrize("flag, is_covered, fullscreen, lifted", [
    (True, False, False, False),     # all fine: leave it alone (no fighting other windows)
    (False, False, False, True),     # Windows dropped "always on top"
    (True, True, False, True),       # another always-on-top window is over the icon
    (False, True, True, False),      # a full-screen app is in front: stay behind it
])
def test_keep_on_top(monkeypatch, flag, is_covered, fullscreen, lifted):
    u = FakeUser32(flag)
    monkeypatch.setattr(topmost, "sys", type("S", (), {"platform": "win32"}))
    monkeypatch.setattr(topmost, "_api", lambda: u)
    monkeypatch.setattr(topmost, "covered", lambda u_, own, ignore: is_covered)
    monkeypatch.setattr(topmost, "fullscreen_app_in_front", lambda u_, own: fullscreen)
    assert topmost.keep_on_top(123) is lifted
    if lifted:   # back to the top of the always-on-top band, never activated (no focus stealing)
        after, flags = u.lifted[0]
        assert after == topmost.HWND_TOPMOST and flags & topmost.SWP_NOACTIVATE


def test_noop_off_windows(monkeypatch):
    monkeypatch.setattr(topmost, "sys", type("S", (), {"platform": "linux"}))
    assert topmost.keep_on_top(123) is False


def test_never_raises(monkeypatch):
    monkeypatch.setattr(topmost, "sys", type("S", (), {"platform": "win32"}))
    monkeypatch.setattr(topmost, "_api", lambda: (_ for _ in ()).throw(OSError("no user32")))
    assert topmost.keep_on_top(123) is False
