import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mygeeky.gui.orbit import OrbitWidget  # noqa: E402

INNER = [("live", "Live", "L", "#ff6fd8"), ("suggestions", "People", "P", "#7fd8ff"),
         ("activity", "Activity", "A", "#34d399"), ("signals", "Signals", "S", "#a78bfa")]
OUTER = [("news", "News", "N", "#eab308"), ("repos", "Repos", "R", "#22c55e"), ("market", "Market", "M", "#ffc457")]


@pytest.fixture
def orbit():
    QApplication.instance() or QApplication([])
    w = OrbitWidget(INNER, OUTER, ("model", "You", "Y", "#ffd24a"))
    w.resize(350, 344)
    w._anim.setDuration(0)
    return w


def test_selecting_brings_the_planet_to_the_lens(orbit):
    orbit.set_selected("market", animate=False)
    lensed = min(orbit._planets(), key=lambda p: (p["ring"] != "outer", -p["y"]))
    assert lensed["id"] == "market"                 # the lowest outer planet is the one in the lens


def test_the_wheel_spins_the_ring_under_the_pointer_and_settles(orbit):
    picked = []
    orbit.selected.connect(picked.append)
    cx, cy, r_in, r_out = orbit._geo()
    pos = QPointF(cx, cy + r_out)                     # over the outer ring
    ev = QWheelEvent(pos, orbit.mapToGlobal(pos), QPoint(0, 0), QPoint(0, 240), Qt.NoButton, Qt.NoModifier,
                     Qt.NoScrollPhase, False)
    orbit.wheelEvent(ev)
    assert orbit.rot["inner"] == 0 and orbit.rot["outer"] != 0
    orbit._settle_wheel()
    assert picked and picked[0] in {"news", "repos", "market"}


def test_clicking_a_planet_selects_it(orbit):
    picked = []
    orbit.selected.connect(picked.append)
    target = next(p for p in orbit._planets() if p["id"] == "activity")
    orbit._drag = {"ring": "inner", "a0": 0.0, "rot0": 0.0, "p0": QPointF(target["x"], target["y"]), "moved": 0.0}

    class E:
        def position(self):
            return QPointF(target["x"], target["y"])
    orbit.mouseReleaseEvent(E())
    assert picked == ["activity"]
