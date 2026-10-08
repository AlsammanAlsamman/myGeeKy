"""The orbit: the panel's tabs as planets on two rings around you.

Your circle (Live, People, Activity, Signals) on the inner ring, the world
(News, Repos, Market) on the outer one, you (your model) in the middle. The
mouse wheel spins whichever ring is under the pointer, dragging spins it too;
when it stops, the planet nearest the lens (the bottom of the ring, pointing
at what you're reading) locks in. Clicking a planet jumps straight to it.

The panel shows its tab bar (the dock) by default; the orbit is the overview,
unfolded on demand, and it folds away again as soon as you open something.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

TAU = 2 * math.pi


class OrbitWidget(QWidget):
    """inner / outer: [(id, label, icon, color)]; center: (id, label, icon, color)."""

    selected = Signal(str)

    def __init__(self, inner: list[tuple[str, str, str, str]], outer: list[tuple[str, str, str, str]],
                 center: tuple[str, str, str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rings = {"inner": inner, "outer": outer}
        self.center = center
        self.rot = {"inner": 0.0, "outer": 0.0}
        self.sel = inner[0][0]
        self.counts: dict[str, int] = {}
        self.letter = "?"
        self.text = QColor("#f0f0f5")
        self.muted = QColor(240, 240, 245, 150)
        self.planet_bg = QColor("#1c1c2c")
        self.setFixedHeight(344)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("Mouse wheel spins a ring · click a planet")
        self._drag: dict | None = None
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(300)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self._anim_ring = "outer"
        self._wheel_ring: str | None = None
        self._wheel_timer = QTimer(self)
        self._wheel_timer.setSingleShot(True)
        self._wheel_timer.setInterval(220)
        self._wheel_timer.timeout.connect(self._settle_wheel)

    # ------------------------------------------------------------------ setup
    def set_theme(self, text: QColor, muted: QColor, dark: bool) -> None:
        self.text, self.muted = text, muted
        self.planet_bg = QColor("#1c1c2c") if dark else QColor("#ffffff")
        self.update()

    def set_counts(self, counts: dict[str, int]) -> None:
        self.counts = dict(counts)
        self.update()

    def set_letter(self, letter: str) -> None:
        self.letter = (letter or "?")[:1].upper()
        self.update()

    def ring_of(self, pid: str) -> str | None:
        for ring, items in self.rings.items():
            if any(p[0] == pid for p in items):
                return ring
        return None

    def set_selected(self, pid: str, animate: bool = True) -> None:
        """Bring `pid` to the lens (no signal: the caller already switched)."""
        self.sel = pid
        ring = self.ring_of(pid)
        if ring:
            i = [p[0] for p in self.rings[ring]].index(pid)
            target = self._target(ring, i)
            if animate and self.isVisible():
                self._spin_to(ring, target)
            else:
                self.rot[ring] = target
        self.update()

    # ------------------------------------------------------------------ geometry
    def _geo(self) -> tuple[float, float, float, float]:
        w, h = self.width(), self.height()
        r_out = min(w - 70, h - 78) / 2
        return w / 2, (h - 16) / 2, r_out * 0.55, r_out

    def _size(self, ring: str, pid: str) -> float:
        base = 21.0 if ring == "inner" else 24.0
        grow = 1 + 0.04 * min(self.counts.get(pid, 0), 6)
        return base * grow * (1.1 if pid == self.sel else 1.0)

    def _planets(self):
        cx, cy, r_in, r_out = self._geo()
        out = []
        for ring, radius in (("outer", r_out), ("inner", r_in)):
            items = self.rings[ring]
            n = len(items)
            for i, (pid, label, icon, color) in enumerate(items):
                th = self.rot[ring] + i * TAU / n + math.pi / 2          # the lens is at the bottom
                # labels go below each planet, except the inner ring's bottom ones: there,
                # below would land on the outer ring's planet in the lens, so above
                above = ring == "inner" and math.sin(th) > 0.7
                out.append({"id": pid, "ring": ring, "i": i, "label": label, "icon": icon, "color": QColor(color), "above": above,
                            "x": cx + radius * math.cos(th), "y": cy + radius * math.sin(th),
                            "r": self._size(ring, pid)})
        return out

    def _target(self, ring: str, i: int) -> float:
        n = len(self.rings[ring])
        want = -i * TAU / n
        return want + round((self.rot[ring] - want) / TAU) * TAU

    def _nearest(self, ring: str) -> int:
        n = len(self.rings[ring])
        return round(-self.rot[ring] / (TAU / n)) % n

    def _ring_at(self, pos: QPointF) -> str | None:
        cx, cy, r_in, r_out = self._geo()
        d = math.hypot(pos.x() - cx, pos.y() - cy)
        if d < 30:
            return "center"
        return "inner" if d < (r_in + r_out) / 2 else "outer"

    # ------------------------------------------------------------------ motion
    def _spin_to(self, ring: str, target: float) -> None:
        self._anim.stop()
        self._anim_ring = ring
        self._anim.setStartValue(float(self.rot[ring]))
        self._anim.setEndValue(float(target))
        self._anim.start()

    def _on_anim(self, value) -> None:
        self.rot[self._anim_ring] = float(value)
        self.update()

    def _lock(self, ring: str, i: int) -> None:
        pid = self.rings[ring][i][0]
        self.sel = pid
        self._spin_to(ring, self._target(ring, i))
        self.selected.emit(pid)

    def _settle_wheel(self) -> None:
        if self._wheel_ring in self.rings:
            self._lock(self._wheel_ring, self._nearest(self._wheel_ring))
        self._wheel_ring = None

    def wheelEvent(self, event) -> None:  # noqa: N802
        ring = self._ring_at(event.position())
        if ring not in self.rings:
            return
        self._anim.stop()
        steps = event.angleDelta().y() / 120 or event.angleDelta().x() / 120
        self.rot[ring] += steps * (TAU / len(self.rings[ring])) * 0.5
        self._wheel_ring = ring
        self._wheel_timer.start()
        self.update()
        event.accept()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        cx, cy, _, _ = self._geo()
        p = event.position()
        ring = self._ring_at(p)
        self._anim.stop()
        self._drag = {"ring": ring, "a0": math.atan2(p.y() - cy, p.x() - cx),
                      "rot0": self.rot.get(ring, 0.0), "p0": p, "moved": 0.0}
        self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        g = self._drag
        if not g or g["ring"] not in self.rings:
            return
        cx, cy, _, _ = self._geo()
        p = event.position()
        g["moved"] = max(g["moved"], math.hypot(p.x() - g["p0"].x(), p.y() - g["p0"].y()))
        da = math.atan2(p.y() - cy, p.x() - cx) - g["a0"]
        da = (da + math.pi) % TAU - math.pi
        self.rot[g["ring"]] = g["rot0"] + da
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        g, self._drag = self._drag, None
        self.setCursor(Qt.OpenHandCursor)
        if not g:
            return
        if g["moved"] < 5:                                   # a click: the planet under the pointer
            p = event.position()
            hit = next((pl for pl in self._planets()
                        if math.hypot(p.x() - pl["x"], p.y() - pl["y"]) <= pl["r"] + 5), None)
            if hit:
                self._lock(hit["ring"], hit["i"])
            elif g["ring"] == "center":
                self.sel = self.center[0]
                self.update()
                self.selected.emit(self.center[0])
            return
        if g["ring"] in self.rings:                           # a spin: the planet nearest the lens
            self._lock(g["ring"], self._nearest(g["ring"]))

    # ------------------------------------------------------------------ painting
    def paintEvent(self, event) -> None:  # noqa: N802
        cx, cy, r_in, r_out = self._geo()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        faint = QColor(self.text)
        faint.setAlpha(40)
        p.setPen(QPen(faint, 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r_out, r_out)
        dashed = QPen(faint, 1, Qt.DashLine)
        p.setPen(dashed)
        p.drawEllipse(QPointF(cx, cy), r_in, r_in)

        planets = self._planets()
        sel_ring = self.ring_of(self.sel)
        if sel_ring:                                          # the lens, under the selected ring
            pl = next(x for x in planets if x["id"] == self.sel)
            radius = r_out if sel_ring == "outer" else r_in
            y = cy + radius + pl["r"] + 5
            p.setPen(Qt.NoPen)
            p.setBrush(pl["color"])
            p.drawRoundedRect(QRectF(cx - 22, y, 44, 6), 3, 3)

        # you, in the middle
        cid, _, _, ccolor = self.center
        on = self.sel == cid
        gold = QColor(ccolor)
        p.setPen(QPen(gold, 2))
        p.setBrush(QColor("#3a3320") if on else self.planet_bg)
        p.drawEllipse(QPointF(cx, cy), 28, 28)
        f = QFont(self.font())
        f.setPixelSize(18)
        f.setBold(True)
        p.setFont(f)
        p.setPen(self.text)
        p.drawText(QRectF(cx - 28, cy - 22, 56, 26), Qt.AlignCenter, self.letter)
        f.setPixelSize(8)
        p.setFont(f)
        p.setPen(self.muted)
        p.drawText(QRectF(cx - 28, cy + 4, 56, 12), Qt.AlignCenter, "YOU")

        emoji = QFont("Segoe UI Emoji")
        label_font = QFont(self.font())
        label_font.setPixelSize(10)
        label_font.setBold(True)
        count_font = QFont(self.font())
        count_font.setPixelSize(9)
        count_font.setBold(True)
        for pl in planets:
            on = pl["id"] == self.sel
            x, y, r, color = pl["x"], pl["y"], pl["r"], pl["color"]
            if on:                                            # a soft halo
                halo = QColor(color)
                halo.setAlpha(60)
                p.setPen(Qt.NoPen)
                p.setBrush(halo)
                p.drawEllipse(QPointF(x, y), r + 6, r + 6)
            p.setPen(QPen(color, 2))
            p.setBrush(color if on else self.planet_bg)
            p.drawEllipse(QPointF(x, y), r, r)
            emoji.setPixelSize(int(r * 0.85))
            p.setFont(emoji)
            p.setPen(self.text)
            p.drawText(QRectF(x - r, y - r, 2 * r, 2 * r), Qt.AlignCenter, pl["icon"])
            n = self.counts.get(pl["id"], 0)
            if n:
                txt = "99+" if n > 99 else str(n)
                w = max(16, 7 * len(txt) + 6)
                box = QRectF(x + r * 0.55, y - r - 2, w, 15)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#f0f0f5"))
                p.drawRoundedRect(box, 7.5, 7.5)
                p.setFont(count_font)
                p.setPen(QColor("#0d0d16"))
                p.drawText(box, Qt.AlignCenter, txt)
            if not on:
                p.setFont(label_font)
                p.setPen(self.muted)
                ly = y - r - 15 if pl["above"] else y + r + 2
                p.drawText(QRectF(x - 45, ly, 90, 13), Qt.AlignHCenter | Qt.AlignTop, pl["label"])
        p.end()
