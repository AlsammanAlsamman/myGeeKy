"""The Qt widget tree for the live glass panel. Kept separate from app.py
so app.py (and its business-logic functions) can be imported/tested without
requiring PySide6 to be importable."""

from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QParallelAnimationGroup,
    QPoint,
    QPointF,
    Qt,
    QPropertyAnimation,
    QRectF,
    QSize,
    QThread,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QGuiApplication,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import app as logic
from .app import THEME_NAMES, THEMES
from ..config import AVATAR_CACHE_DIR, MyGeekyConfig

ASSETS_DIR = Path(__file__).parent / "assets"
ICON_WINDOW = ASSETS_DIR / "icon_64.png"
ICON_HEADER = ASSETS_DIR / "icon_32.png"
ICON_FOLDED = ASSETS_DIR / "icon_128.png"   # drawn at ~58px: start large so it downscales crisply

SWATCH_GRADIENTS = {
    "frosted": "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #fff6ee, stop:1 #cfe0ff)",
    "midnight": "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #2a2a3d, stop:1 #0c0c14)",
    "aurora": "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #ff6fd8, stop:0.5 #7a5cff, stop:1 #35e0c1)",
}

AVATAR_PALETTE = ["#e08a4f", "#7aa6e0", "#5ac8a8", "#ff6fd8", "#7a5cff", "#35c2e0", "#e05c5c"]


def _build_spotlight_items(activity_events: list[dict[str, Any]],
                            suggestions: list[dict[str, Any]],
                            signals: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Normalizes activity events and follow-back suggestions into one
    interleaved rotation for the Live tab's ticker: recent real activity
    (pushes, merges, new repos, releases, stars -- already exactly "what
    they've been working on" and "repos they starred", straight from
    GitHub's events feed) alternated with top suggestions, so the ticker
    doesn't just show one or the other for several slides in a row."""
    activity_items = [{
        "kind": "activity",
        "username": e.get("actor", ""),
        "avatar_url": e.get("actor_avatar", ""),
        "profile_url": e.get("profile_url", ""),
        "headline": (e.get("verb", "") + (f" in {e['repo']}" if e.get("repo") else "")).strip(),
        "detail": "",
        "time_text": _time_ago(e.get("created_at", "")),
    } for e in activity_events]

    suggestion_items = [{
        "kind": "suggestion",
        "username": s.get("username", ""),
        "avatar_url": s.get("avatar_url", ""),
        "profile_url": s.get("profile_url", ""),
        "headline": f"might follow back · score {s['score']:.2f}" if isinstance(s.get("score"), (int, float))
                    else "matches your profile",
        "detail": (s.get("bio") or "")[:70],
        "time_text": "",
    } for s in suggestions]

    # signals people sent you lead the rotation -- they're about you
    interleaved: list[dict[str, Any]] = [{
        "kind": "signal",
        "username": s.get("from", ""),
        "avatar_url": s.get("avatar_url", ""),
        "profile_url": s.get("profile_url", ""),
        "headline": s.get("text", "") + ("  🤝" if s.get("mutual") else ""),
        "detail": "",
        "time_text": _time_ago(s.get("at", "")),
    } for s in (signals or [])[:5]]
    i = j = 0
    while i < len(activity_items) or j < len(suggestion_items):
        if i < len(activity_items):
            interleaved.append(activity_items[i])
            i += 1
        if j < len(suggestion_items):
            interleaved.append(suggestion_items[j])
            j += 1
    return interleaved


def _time_ago(iso: str) -> str:
    if not iso:
        return ""
    try:
        then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    now = datetime.now(then.tzinfo) if then.tzinfo else datetime.now()
    diff = max(0.0, (now - then).total_seconds())
    if diff < 60:
        return "just now"
    if diff < 3600:
        return f"{int(diff // 60)}m ago"
    if diff < 86400:
        return f"{int(diff // 3600)}h ago"
    return f"{int(diff // 86400)}d ago"


def _avatar_color(name: str) -> str:
    if not name:
        return AVATAR_PALETTE[0]
    return AVATAR_PALETTE[sum(ord(c) for c in name) % len(AVATAR_PALETTE)]


def _avatar_label(username: str, size: int = 32) -> QLabel:
    """The immediate, always-available fallback: a colored circle with initials.
    `_avatar_widget` below upgrades this to a real photo once one loads."""
    parts = [p for p in username.replace("-", " ").replace("_", " ").split() if p]
    initials = "".join(p[0] for p in parts[:2]).upper() or "?"
    label = QLabel(initials)
    label.setFixedSize(size, size)
    label.setAlignment(Qt.AlignCenter)
    label.setStyleSheet(
        f"background:{_avatar_color(username)}; color:white; border-radius:{size // 2}px; "
        f"font-weight:700; font-size:{max(9, size // 3)}px;"
    )
    return label


def _circular_pixmap(source: QPixmap, size: int) -> QPixmap:
    """Crop + mask a square photo into a smooth circle with transparent corners."""
    scaled = source.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x = max(0, (scaled.width() - size) // 2)
    y = max(0, (scaled.height() - size) // 2)
    cropped = scaled.copy(x, y, size, size)

    result = QPixmap(size, size)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addEllipse(0, 0, size, size)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, cropped)
    painter.end()
    return result


def _avatar_widget(username: str, avatar_url: str, size: int, loader: "AvatarLoader | None") -> QLabel:
    """Starts as the colored-initials fallback, upgraded in place to the
    person's real GitHub photo once it loads (async, cached)."""
    label = _avatar_label(username, size)
    if loader and avatar_url:
        def _apply(pixmap: QPixmap) -> None:
            try:
                label.setPixmap(pixmap)
                label.setText("")
                label.setStyleSheet("background: transparent;")
            except RuntimeError:
                pass  # the widget was already destroyed (e.g. ticker rotated past it)

        loader.request(avatar_url, size, _apply)
    return label


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()  # deleteLater only runs on a later event-loop turn
            widget.deleteLater()


class _Worker(QThread):
    """Runs one callable off the UI thread so a slow network call (a real
    `mygeeky run`, or an activity-feed fetch) never freezes the panel."""

    done = Signal(object)

    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:  # keep the worker thread from ever crashing the app
            result = {"error": str(exc)}
        self.done.emit(result)


class AvatarLoader:
    """Fetches GitHub avatar photos off the UI thread. Cached in memory for
    this session and on disk (`AVATAR_CACHE_DIR`) across restarts, so the
    same photo is only ever downloaded once."""

    def __init__(self) -> None:
        self._memory: dict[str, QPixmap] = {}
        self._workers: list[_Worker] = []

    def request(self, url: str, size: int, on_loaded: Callable[[QPixmap], None]) -> None:
        if not url:
            return
        cache_key = f"{url}@{size}"
        cached = self._memory.get(cache_key)
        if cached is not None:
            on_loaded(cached)
            return

        disk_path = AVATAR_CACHE_DIR / (hashlib.sha1(cache_key.encode()).hexdigest() + ".png")

        def fetch() -> QPixmap | None:
            if disk_path.exists():
                pm = QPixmap(str(disk_path))
                if not pm.isNull():
                    return pm
            try:
                import requests
                resp = requests.get(url, timeout=6)
                resp.raise_for_status()
            except Exception:
                return None
            raw = QPixmap()
            if not raw.loadFromData(resp.content):
                return None
            circular = _circular_pixmap(raw, size)
            try:
                AVATAR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                circular.save(str(disk_path), "PNG")
            except OSError:
                pass
            return circular

        worker = _Worker(fetch)

        def _finish(result: Any) -> None:
            if isinstance(result, QPixmap) and not result.isNull():
                self._memory[cache_key] = result
                on_loaded(result)
            if worker in self._workers:
                self._workers.remove(worker)

        worker.done.connect(_finish)
        self._workers.append(worker)
        worker.start()


def _auc_color(auc: float | None) -> QColor:
    """Grade colour shared by the gauge and the verdict chip."""
    if auc is None:
        return QColor("#9ca3af")
    if auc >= 0.8:
        return QColor("#34d399")
    if auc >= 0.7:
        return QColor("#60a5fa")
    if auc >= 0.6:
        return QColor("#fbbf24")
    return QColor("#f87171")


class _Pulse:
    """A slow 0..1..0 breathing phase that only ticks while the widget is
    visible, so the idle panel costs no CPU."""

    def __init__(self, widget: QWidget, period_ms: int = 2400) -> None:
        self._widget = widget
        self._period = period_ms
        self._t = 0
        self._timer = QTimer(widget)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    def _tick(self) -> None:
        self._t = (self._t + 40) % self._period
        self._widget.update()

    @property
    def phase(self) -> float:
        return 0.5 - 0.5 * math.cos(2 * math.pi * self._t / self._period)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()


def _grow_animation(owner: QWidget, setter: Callable[[float], None], ms: int = 900) -> QVariantAnimation:
    anim = QVariantAnimation(owner)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setDuration(ms)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    anim.valueChanged.connect(lambda v: setter(float(v)))
    return anim


def _short_date(entry: dict[str, Any]) -> str:
    try:
        return datetime.fromisoformat(entry.get("timestamp", "")).strftime("%b %d")
    except (TypeError, ValueError):
        return ""


class AucGauge(QWidget):
    """Ring gauge for the cross-validated AUC: sweeps in when played and
    softly glows, coloured by grade."""

    def __init__(self, size: int = 112) -> None:
        super().__init__()
        self.setFixedSize(size, size)
        self._auc: float | None = None
        self._progress = 1.0
        self._text_color = QColor("#f0f0f5")
        self._pulse = _Pulse(self)
        self._anim = _grow_animation(self, self._set_progress, 1100)

    def _set_progress(self, v: float) -> None:
        self._progress = v
        self.update()

    def set_theme_colors(self, text_color: str) -> None:
        self._text_color = QColor(text_color)
        self.update()

    def set_auc(self, auc: float | None) -> None:
        self._auc = auc
        self.update()

    def play(self) -> None:
        self._anim.stop()
        self._anim.start()

    def showEvent(self, event) -> None:  # noqa: N802 -- Qt's own naming convention
        self._pulse.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._pulse.stop()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height())
        ring = QRectF(12, 12, side - 24, side - 24)
        color = _auc_color(self._auc)

        track = QColor(self._text_color)
        track.setAlpha(28)
        painter.setPen(QPen(track, 9, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(ring, 0, 360 * 16)

        if self._auc is not None:
            span = -int(360 * 16 * max(0.0, min(1.0, self._auc)) * self._progress)
            glow = QColor(color)
            glow.setAlpha(int(35 + 55 * self._pulse.phase))
            painter.setPen(QPen(glow, 17, Qt.SolidLine, Qt.RoundCap))
            painter.drawArc(ring, 90 * 16, span)
            painter.setPen(QPen(color, 9, Qt.SolidLine, Qt.RoundCap))
            painter.drawArc(ring, 90 * 16, span)

        value = "–" if self._auc is None else f"{self._auc * self._progress:.3f}"
        font = painter.font()
        font.setPixelSize(22)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(self._text_color)
        painter.drawText(QRectF(0, side / 2 - 18, side, 26), Qt.AlignCenter, value)
        font.setPixelSize(10)
        font.setBold(False)
        painter.setFont(font)
        muted = QColor(self._text_color)
        muted.setAlpha(150)
        painter.setPen(muted)
        painter.drawText(QRectF(0, side / 2 + 8, side, 14), Qt.AlignCenter, "AUC")
        painter.end()


class StatTile(QFrame):
    """A small number + caption tile whose number counts up when played."""

    def __init__(self, caption: str) -> None:
        super().__init__()
        self.setObjectName("statTile")
        box = QVBoxLayout(self)
        box.setContentsMargins(8, 6, 8, 6)
        box.setSpacing(0)
        self.value_label = QLabel("–")
        self.caption_label = QLabel(caption)
        box.addWidget(self.value_label)
        box.addWidget(self.caption_label)
        self._target = 0.0
        self._fmt: Callable[[float], str] = lambda v: f"{v:.0f}"
        self._anim = _grow_animation(self, self._render, 1000)

    def set_value(self, value: float, fmt: Callable[[float], str] | None = None) -> None:
        self._target = value
        if fmt:
            self._fmt = fmt
        self._render(1.0)

    def _render(self, progress: float) -> None:
        self.value_label.setText(self._fmt(self._target * progress))

    def play(self) -> None:
        self._anim.stop()
        self._anim.start()

    def apply_theme(self, theme: dict[str, Any]) -> None:
        self.setStyleSheet(f"QFrame#statTile {{ background:{theme['card_bg']}; border-radius:10px; }}")
        self.value_label.setStyleSheet(
            f"color:{theme['text']}; font-size:16px; font-weight:600; background:transparent;")
        self.caption_label.setStyleSheet(f"color:{theme['muted']}; font-size:10px; background:transparent;")


class WeightBars(QWidget):
    """Diverging bars of what the model rewards (right) and penalizes
    (left), growing out from a centre line when played."""

    ROW = 24

    def __init__(self) -> None:
        super().__init__()
        self._weights: list[dict[str, Any]] = []
        self._progress = 1.0
        self._text_color = QColor("#f0f0f5")
        self._accent = QColor("#7fd8ff")
        self._anim = _grow_animation(self, self._set_progress, 1000)
        self.setFixedHeight(self.ROW + 4)

    def _set_progress(self, v: float) -> None:
        self._progress = v
        self.update()

    def set_theme_colors(self, text_color: str, accent_color: str) -> None:
        self._text_color = QColor(text_color)
        self._accent = QColor(accent_color)
        self.update()

    def set_weights(self, weights: list[dict[str, Any]]) -> None:
        self._weights = weights
        self.setFixedHeight(max(1, len(weights)) * self.ROW + 4)
        self.update()

    def play(self) -> None:
        self._anim.stop()
        self._anim.start()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        muted = QColor(self._text_color)
        muted.setAlpha(150)
        font = painter.font()
        font.setPixelSize(11)
        painter.setFont(font)
        if not self._weights:
            painter.setPen(muted)
            painter.drawText(QRectF(self.rect()), Qt.AlignLeft | Qt.AlignVCenter, "No trained model yet.")
            painter.end()
            return

        w = self.width()
        label_w = w * 0.42
        mid = label_w + (w - label_w) / 2
        half = (w - label_w) / 2 - 34
        biggest = max(abs(x["weight"]) for x in self._weights) or 1.0
        negative = QColor("#f87171")

        for i, item in enumerate(self._weights):
            y = i * self.ROW + 2
            positive = item["weight"] >= 0
            painter.setPen(self._text_color)
            painter.drawText(QRectF(0, y, label_w - 6, self.ROW), Qt.AlignLeft | Qt.AlignVCenter, item["label"])
            length = half * abs(item["weight"]) / biggest * self._progress
            color = QColor(self._accent if positive else negative)
            faded = QColor(color)
            faded.setAlpha(110)
            grad = QLinearGradient(mid, 0, mid + length if positive else mid - length, 0)
            grad.setColorAt(0, faded)
            grad.setColorAt(1, color)
            bar = QRectF(mid, y + 6, length, self.ROW - 12) if positive \
                else QRectF(mid - length, y + 6, length, self.ROW - 12)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(grad))
            painter.drawRoundedRect(bar, 4, 4)
            painter.setPen(muted)
            text = f"{item['weight']:+.2f}"
            if positive:
                painter.drawText(QRectF(bar.right() + 4, y, 40, self.ROW), Qt.AlignLeft | Qt.AlignVCenter, text)
            else:
                painter.drawText(QRectF(bar.left() - 44, y, 40, self.ROW), Qt.AlignRight | Qt.AlignVCenter, text)

        axis = QColor(self._text_color)
        axis.setAlpha(60)
        painter.setPen(QPen(axis, 1))
        painter.drawLine(QPointF(mid, 0), QPointF(mid, self.height()))
        painter.end()


class TrendChart(QWidget):
    """Hand-drawn AUC-over-time chart -- no charting dependency needed. A
    smooth line over faint training-set-size bars, a zoomed y-axis with the
    coin-flip line, a pulsing newest point, a draw-in animation and a hover
    tooltip."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(150)
        self.setMouseTracking(True)
        self._history: list[dict[str, Any]] = []
        self._points: list[float] = []
        self._text_color = QColor("#f0f0f5")
        self._accent_color = QColor("#7fd8ff")
        self._progress = 1.0
        self._hover: int | None = None
        self._pulse = _Pulse(self, 1600)
        self._anim = _grow_animation(self, self._set_progress, 1200)

    def _set_progress(self, v: float) -> None:
        self._progress = v
        self.update()

    def set_theme_colors(self, text_color: str, accent_color: str) -> None:
        self._text_color = QColor(text_color)
        self._accent_color = QColor(accent_color)
        self.update()

    def set_history(self, history: list[dict[str, Any]]) -> None:
        self._history = [h for h in history if h.get("auc") is not None]
        self._points = [h["auc"] for h in self._history]
        self._hover = None
        self.update()

    def play(self) -> None:
        self._anim.stop()
        self._anim.start()

    def showEvent(self, event) -> None:  # noqa: N802
        self._pulse.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._pulse.stop()
        super().hideEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = None
        self.update()

    def _bounds(self) -> tuple[float, float, float, float, float, float]:
        left, right, top, bottom = 34.0, 10.0, 12.0, 18.0
        lo = min(self._points + [0.5]) - 0.03
        hi = max(self._points) + 0.03
        if hi - lo < 0.1:
            hi = lo + 0.1
        return left, right, top, bottom, max(0.0, lo), min(1.0, hi)

    def _xy(self) -> tuple[list[float], list[float]]:
        left, right, top, bottom, lo, hi = self._bounds()
        w, h = self.width(), self.height()
        n = len(self._points)
        if n == 1:
            xs = [left + (w - left - right) / 2]
        else:
            xs = [left + (i / (n - 1)) * (w - left - right) for i in range(n)]
        ys = [top + (1 - (p - lo) / (hi - lo)) * (h - top - bottom) for p in self._points]
        return xs, ys

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self._points:
            return
        xs, _ = self._xy()
        x = event.position().x()
        self._hover = min(range(len(xs)), key=lambda i: abs(xs[i] - x))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        muted = QColor(self._text_color)
        muted.setAlpha(140)
        font = painter.font()
        font.setPixelSize(10)
        painter.setFont(font)

        if not self._points:
            painter.setPen(muted)
            painter.drawText(QRectF(self.rect()), Qt.AlignCenter, "No retrains yet to chart")
            painter.end()
            return

        left, right, top, bottom, lo, hi = self._bounds()
        plot_h = h - top - bottom
        grid = QColor(self._text_color)
        grid.setAlpha(26)
        for k in range(3):
            v = lo + (hi - lo) * k / 2
            y = top + (1 - k / 2) * plot_h
            painter.setPen(QPen(grid, 1))
            painter.drawLine(QPointF(left, y), QPointF(w - right, y))
            painter.setPen(muted)
            painter.drawText(QRectF(0, y - 7, left - 6, 14), Qt.AlignRight | Qt.AlignVCenter, f"{v:.2f}")

        if lo <= 0.5 <= hi:  # the coin-flip line the model has to beat
            y = top + (1 - (0.5 - lo) / (hi - lo)) * plot_h
            painter.setPen(QPen(muted, 1, Qt.DashLine))
            painter.drawLine(QPointF(left, y), QPointF(w - right, y))
            painter.drawText(QRectF(left + 4, y - 14, 80, 12), Qt.AlignLeft, "chance")

        xs, ys = self._xy()
        n = len(xs)

        # faint bars: how many labelled examples each retrain learned from
        sizes = [entry.get("n_train") or 0 for entry in self._history]
        biggest = max(sizes) or 1
        bar_w = max(4.0, min(18.0, (w - left - right) / n * 0.35))
        bar_color = QColor(self._accent_color)
        bar_color.setAlpha(24)
        painter.setPen(Qt.NoPen)
        painter.setBrush(bar_color)
        for x, size in zip(xs, sizes):
            bh = plot_h * 0.45 * size / biggest * self._progress
            painter.drawRoundedRect(QRectF(x - bar_w / 2, top + plot_h - bh, bar_w, bh), 2, 2)

        painter.save()
        painter.setClipRect(QRectF(0, 0, left + (w - left - right) * self._progress + 4, h))
        if n > 1:
            line = QPainterPath(QPointF(xs[0], ys[0]))
            for i in range(1, n):
                cx = (xs[i - 1] + xs[i]) / 2
                line.cubicTo(QPointF(cx, ys[i - 1]), QPointF(cx, ys[i]), QPointF(xs[i], ys[i]))
            area = QPainterPath(line)
            area.lineTo(xs[-1], top + plot_h)
            area.lineTo(xs[0], top + plot_h)
            area.closeSubpath()
            fill = QLinearGradient(0, top, 0, top + plot_h)
            strong = QColor(self._accent_color)
            strong.setAlpha(110)
            clear = QColor(self._accent_color)
            clear.setAlpha(0)
            fill.setColorAt(0, strong)
            fill.setColorAt(1, clear)
            painter.fillPath(area, QBrush(fill))
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(self._accent_color, 2.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(line)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._accent_color)
        for x, y in zip(xs, ys):
            painter.drawEllipse(QPointF(x, y), 3, 3)
        painter.restore()

        if self._progress >= 0.999:  # the newest retrain breathes
            phase = self._pulse.phase
            halo = QColor(self._accent_color)
            halo.setAlpha(int(150 * (1 - phase)))
            painter.setPen(Qt.NoPen)
            painter.setBrush(halo)
            painter.drawEllipse(QPointF(xs[-1], ys[-1]), 4 + 7 * phase, 4 + 7 * phase)
            painter.setBrush(self._accent_color)
            painter.drawEllipse(QPointF(xs[-1], ys[-1]), 4.5, 4.5)

        painter.setPen(muted)
        painter.drawText(QRectF(left, h - 14, 90, 14), Qt.AlignLeft, _short_date(self._history[0]))
        if n > 1:
            painter.drawText(QRectF(w - right - 90, h - 14, 90, 14), Qt.AlignRight, _short_date(self._history[-1]))

        if self._hover is not None and self._hover < n:
            i = self._hover
            guide = QColor(self._text_color)
            guide.setAlpha(70)
            painter.setPen(QPen(guide, 1, Qt.DotLine))
            painter.drawLine(QPointF(xs[i], top), QPointF(xs[i], top + plot_h))
            entry = self._history[i]
            text = f"AUC {entry['auc']:.3f} · {entry.get('n_train', '?')} examples · {_short_date(entry)}"
            tw = painter.fontMetrics().horizontalAdvance(text) + 14
            tx = min(max(xs[i] - tw / 2, 0), w - tw)
            ty = max(ys[i] - 30, 0)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(20, 20, 30, 225))
            painter.drawRoundedRect(QRectF(tx, ty, tw, 20), 6, 6)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(QRectF(tx, ty, tw, 20), Qt.AlignCenter, text)
        painter.end()


class SuggestionCard(QFrame):
    """Clicking anywhere on the card opens the profile; the panel then drops
    the person from the suggestions (see MyGeekyPanel._on_suggestion_clicked)."""

    def __init__(self, item: dict[str, Any], score_key: str, theme: dict[str, Any],
                 on_click: Callable[[dict[str, Any]], None], loader: "AvatarLoader | None" = None) -> None:
        super().__init__()
        self.setObjectName("card")
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 8, 8, 8)
        row.setSpacing(8)
        row.addWidget(_avatar_widget(item.get("username", "?"), item.get("avatar_url", ""), 32, loader))

        body = QVBoxLayout()
        body.setSpacing(2)
        title_row = QHBoxLayout()
        name_label = QLabel(item.get("username", ""))
        name_label.setStyleSheet("font-weight:600; font-size:12.5px; background:transparent;")
        score = item.get(score_key)
        score_label = QLabel(f"{score:.2f}" if isinstance(score, (int, float)) else "")
        score_label.setStyleSheet(f"color:{theme['muted']}; font-size:12px; background:transparent;")
        title_row.addWidget(name_label)
        title_row.addStretch(1)
        title_row.addWidget(score_label)
        body.addLayout(title_row)

        bio_label = QLabel((item.get("bio") or "")[:80])
        bio_label.setWordWrap(True)  # a long bio must not widen the card past the panel
        bio_label.setStyleSheet(f"color:{theme['muted']}; font-size:11px; background:transparent;")
        body.addWidget(bio_label)
        row.addLayout(body, 1)

        self.setStyleSheet(f"#card {{ background:{theme['card_bg']}; border-radius:10px; }}"
                           f"#card:hover {{ background:{theme['btn_bg']}; }}")
        self.setToolTip("Open profile")
        self.setCursor(Qt.PointingHandCursor)
        self.mousePressEvent = lambda ev: on_click(item)  # noqa: ARG005


class _ActivityRow(QFrame):
    """One event inside an expanded person card; clicking opens the repo."""

    def __init__(self, event: dict[str, Any], theme: dict[str, Any], on_open: Callable[[str], bool]) -> None:
        super().__init__()
        self.setObjectName("activityRow")
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(8)
        verb = event.get("verb", "")
        repo = event.get("repo", "")
        text = QLabel(verb + (f" in <b>{repo}</b>" if repo else ""))
        text.setWordWrap(True)
        text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        text.setStyleSheet(f"color:{theme['text']}; font-size:11px; background:transparent;")
        row.addWidget(text, 1)
        when = QLabel(_time_ago(event.get("created_at", "")))
        when.setStyleSheet(f"color:{theme['muted']}; font-size:10px; background:transparent;")
        row.addWidget(when, 0, Qt.AlignTop)
        self.setStyleSheet(f"QFrame#activityRow {{ border-radius:6px; }}"
                           f"QFrame#activityRow:hover {{ background:{theme['btn_bg']}; }}")
        self.setCursor(Qt.PointingHandCursor)
        url = event.get("repo_url") or event.get("profile_url", "")
        self.mousePressEvent = lambda ev: on_open(url)  # noqa: ARG005


class ActivityGroup(QFrame):
    """One person in the Activity tab: avatar, name, a one-line summary of
    their latest event and how many there are. Clicking the header expands
    their full recent activity; the arrow button opens their profile."""

    toggled = Signal(str, bool)

    def __init__(self, group: dict[str, Any], theme: dict[str, Any], on_open: Callable[[str], bool],
                 loader: "AvatarLoader | None" = None, expanded: bool = False) -> None:
        super().__init__()
        self.setObjectName("activityGroup")
        self.actor = group.get("actor", "")
        events = group.get("events") or []
        latest = events[0] if events else {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 7, 8, 7)
        outer.setSpacing(4)

        self.header = QWidget()
        self.header.setCursor(Qt.PointingHandCursor)
        head = QHBoxLayout(self.header)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        head.addWidget(_avatar_widget(self.actor or "?", group.get("actor_avatar", ""), 30, loader))

        text_box = QVBoxLayout()
        text_box.setSpacing(1)
        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        name = QLabel(self.actor)
        name.setStyleSheet(f"color:{theme['text']}; font-size:12px; font-weight:600; background:transparent;")
        name_row.addWidget(name)
        is_match = group.get("source") == "match"
        tag = QLabel("profile match" if is_match else "following")
        tag.setStyleSheet(
            f"color:{theme['text']}; background:{theme['section_btn'] if is_match else theme['btn_bg']}; "
            f"border-radius:7px; padding:1px 6px; font-size:9.5px;")
        tag.setFixedHeight(16)
        name_row.addWidget(tag)
        name_row.addStretch(1)
        text_box.addLayout(name_row)
        summary = latest.get("verb", "")
        if latest.get("repo"):
            summary += f" in {latest['repo'].split('/')[-1]}"
        self.summary_label = QLabel(f"{summary} · {_time_ago(latest.get('created_at', ''))}")
        self.summary_label.setWordWrap(True)  # long branch names must not widen the card past the panel
        self.summary_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.summary_label.setStyleSheet(f"color:{theme['muted']}; font-size:10.5px; background:transparent;")
        text_box.addWidget(self.summary_label)
        head.addLayout(text_box, 1)

        count = QLabel(str(len(events)))
        count.setAlignment(Qt.AlignCenter)
        count.setMinimumWidth(22)
        count.setFixedHeight(18)
        count.setStyleSheet(f"color:{theme['text']}; background:{theme['btn_bg']}; border-radius:9px; "
                            f"padding:1px 6px; font-size:10.5px; font-weight:600;")
        count.setToolTip(f"{len(events)} recent update{'s' if len(events) != 1 else ''}")
        head.addWidget(count)
        self.chevron = QLabel()
        self.chevron.setStyleSheet(f"color:{theme['muted']}; font-size:12px; background:transparent;")
        head.addWidget(self.chevron)
        profile_btn = QPushButton("↗")
        profile_btn.setToolTip(f"Open {self.actor}'s GitHub profile")
        profile_btn.setCursor(Qt.PointingHandCursor)
        profile_btn.setFixedSize(24, 24)
        profile_btn.setStyleSheet(
            f"QPushButton {{ background:{theme['btn_bg']}; color:{theme['text']}; border:none; "
            f"border-radius:12px; font-size:12px; }}"
            f"QPushButton:hover {{ background:{theme['btn_hover']}; }}")
        profile_url = group.get("profile_url", "")
        profile_btn.clicked.connect(lambda: on_open(profile_url))
        head.addWidget(profile_btn)
        outer.addWidget(self.header)

        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(30, 2, 0, 0)
        body.setSpacing(0)
        for event in events:
            body.addWidget(_ActivityRow(event, theme, on_open))
        outer.addWidget(self.body)

        self.setStyleSheet(f"QFrame#activityGroup {{ background:{theme['card_bg']}; border-radius:10px; }}")
        self.header.mousePressEvent = lambda ev: self.set_expanded(not self.expanded, notify=True)  # noqa: ARG005
        self.expanded = False
        self.set_expanded(expanded)

    def set_expanded(self, expanded: bool, notify: bool = False) -> None:
        self.expanded = expanded
        self.body.setVisible(expanded)
        self.summary_label.setVisible(not expanded)
        self.chevron.setText("▾" if expanded else "▸")
        if notify:
            self.toggled.emit(self.actor, expanded)


PANEL_GESTURES = ("wave", "learn", "collab", "watching")  # kudos needs a repo: CLI only


class SignalCard(QFrame):
    """One person on the Signals tab: an incoming signal (with a handshake
    badge when it's mutual) or a fellow myGeeKy user. The emoji buttons
    send a signal back; the arrow opens their profile. Everything shown
    from someone's beacon is rendered as plain text."""

    def __init__(self, item: dict[str, Any], theme: dict[str, Any], on_open: Callable[[str], bool],
                 on_send: Callable[["SignalCard", str, str], None] | None,
                 loader: "AvatarLoader | None" = None) -> None:
        super().__init__()
        from ..beacon import GESTURES
        self.setObjectName("signalCard")
        self.login = item.get("from") or item.get("login") or ""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 7, 8, 7)
        outer.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(_avatar_widget(self.login or "?", item.get("avatar_url", ""), 30, loader))
        text_box = QVBoxLayout()
        text_box.setSpacing(1)
        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        name = QLabel(self.login)
        name.setTextFormat(Qt.PlainText)
        name.setStyleSheet(f"color:{theme['text']}; font-size:12px; font-weight:600; background:transparent;")
        name_row.addWidget(name)
        badge_text = "🤝 handshake" if item.get("mutual") else "signalled you" if item.get("signalled_you") else ""
        if badge_text:
            badge = QLabel(badge_text)
            badge.setStyleSheet(f"color:{theme['text']}; background:{theme['section_btn']}; "
                                f"border-radius:7px; padding:1px 6px; font-size:9.5px;")
            badge.setFixedHeight(16)
            name_row.addWidget(badge)
        name_row.addStretch(1)
        text_box.addLayout(name_row)

        if "text" in item:  # an incoming signal
            line = f"{item['text']} · {_time_ago(item.get('at', ''))}"
        else:               # a fellow user
            shared = item.get("shared") or []
            line = " · ".join(x for x in (item.get("status", ""),
                                          f"shares {', '.join(shared[:4])}" if shared else
                                          ", ".join((item.get("interests") or [])[:4])) if x)
        sub = QLabel(line)
        sub.setTextFormat(Qt.PlainText)
        sub.setWordWrap(True)
        sub.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        sub.setStyleSheet(f"color:{theme['muted']}; font-size:10.5px; background:transparent;")
        text_box.addWidget(sub)
        head.addLayout(text_box, 1)

        profile_btn = QPushButton("↗")
        profile_btn.setToolTip(f"Open {self.login}'s GitHub profile")
        profile_btn.setCursor(Qt.PointingHandCursor)
        profile_btn.setFixedSize(24, 24)
        btn_style = (f"QPushButton {{ background:{theme['btn_bg']}; color:{theme['text']}; border:none; "
                     f"border-radius:12px; font-size:12px; }}"
                     f"QPushButton:hover {{ background:{theme['btn_hover']}; }}"
                     f"QPushButton:disabled {{ color:{theme['muted']}; }}")
        profile_btn.setStyleSheet(btn_style)
        profile_url = item.get("profile_url", "")
        profile_btn.clicked.connect(lambda: on_open(profile_url))
        head.addWidget(profile_btn)
        outer.addLayout(head)

        self.gesture_buttons: dict[str, QPushButton] = {}
        if on_send is not None:
            row = QHBoxLayout()
            row.setContentsMargins(38, 0, 0, 0)
            row.setSpacing(4)
            for g in PANEL_GESTURES:
                emoji, verb = GESTURES[g]
                btn = QPushButton(emoji)
                btn.setFixedSize(28, 24)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setToolTip(f"Send {self.login} a '{g}' signal (public)")
                btn.setStyleSheet(btn_style)
                btn.clicked.connect(lambda checked=False, gg=g: on_send(self, self.login, gg))
                self.gesture_buttons[g] = btn
                row.addWidget(btn)
            row.addStretch(1)
            self.feedback = QLabel("")
            self.feedback.setStyleSheet(f"color:{theme['muted']}; font-size:10px; background:transparent;")
            row.addWidget(self.feedback)
            outer.addLayout(row)

        self.setStyleSheet(f"QFrame#signalCard {{ background:{theme['card_bg']}; border-radius:10px; }}")

    def set_busy(self, busy: bool) -> None:
        for btn in self.gesture_buttons.values():
            btn.setEnabled(not busy)

    def show_result(self, text: str) -> None:
        self.feedback.setText(text)


UP_COLOR = "#34d399"
DOWN_COLOR = "#f87171"


def _fmt_count(n: float | None) -> str:
    if n is None:
        return "–"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return f"{n:.0f}"


class Sparkline(QWidget):
    """A tiny trend line with a soft fill, green when rising, red when falling."""

    def __init__(self, values: list[float], trend: str | None = None, width: int = 64, height: int = 22) -> None:
        super().__init__()
        self.setFixedSize(width, height)
        self._values = [float(v) for v in values]
        self._trend = trend

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt's own naming convention
        if len(self._values) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        lo, hi = min(self._values), max(self._values)
        span = (hi - lo) or 1.0
        n = len(self._values)
        pts = [QPointF(2 + i * (w - 4) / (n - 1), h - 2 - (v - lo) / span * (h - 4))
               for i, v in enumerate(self._values)]
        if self._trend is None:
            color = QColor(150, 150, 165)  # no comparable period: neutral
        else:
            color = QColor(UP_COLOR if self._trend == "up" else DOWN_COLOR)
        line = QPainterPath(pts[0])
        for p in pts[1:]:
            line.lineTo(p)
        area = QPainterPath(line)
        area.lineTo(pts[-1].x(), h)
        area.lineTo(pts[0].x(), h)
        area.closeSubpath()
        fill = QColor(color)
        fill.setAlpha(45)
        painter.fillPath(area, fill)
        painter.setPen(QPen(color, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(line)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(pts[-1], 2.2, 2.2)
        painter.end()


class MarketRow(QFrame):
    """One repo on the board: rank, movement since the last ranked day,
    name, stars (+ this week), PyPI downloads/week (+ change), commits and a
    sparkline. Clicking opens the repo."""

    def __init__(self, row: dict[str, Any], theme: dict[str, Any], on_open: Callable[[str], bool],
                 loader: "AvatarLoader | None" = None) -> None:
        super().__init__()
        self.setObjectName("marketRow")
        self.repo = row.get("repo", "")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(8)

        rank_box = QVBoxLayout()
        rank_box.setSpacing(0)
        rank = QLabel(f"#{row.get('rank', '?')}")
        rank.setAlignment(Qt.AlignCenter)
        rank.setStyleSheet(f"color:{theme['text']}; font-size:12px; font-weight:700; background:transparent;")
        rank_box.addWidget(rank)
        move = row.get("movement")
        if move == "new":
            move_text, move_color = "NEW", theme["accent"]
        elif isinstance(move, int) and move > 0:
            move_text, move_color = f"▲{move}", UP_COLOR
        elif isinstance(move, int) and move < 0:
            move_text, move_color = f"▼{-move}", DOWN_COLOR
        else:
            move_text, move_color = "–", theme["muted"]
        move_label = QLabel(move_text)
        move_label.setAlignment(Qt.AlignCenter)
        move_label.setStyleSheet(f"color:{move_color}; font-size:9.5px; font-weight:600; background:transparent;")
        rank_box.addWidget(move_label)
        rank_holder = QWidget()
        rank_holder.setLayout(rank_box)
        rank_holder.setFixedWidth(30)
        outer.addWidget(rank_holder)

        owner, _, name = self.repo.partition("/")
        outer.addWidget(_avatar_widget(owner or "?", row.get("avatar", ""), 26, loader))

        body = QVBoxLayout()
        body.setSpacing(1)
        title = QLabel(f"<b>{name}</b> <span style='color:{theme['muted']}'>{owner}</span>")
        title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        title.setStyleSheet(f"color:{theme['text']}; font-size:11.5px; background:transparent;")
        title.setToolTip(row.get("description", ""))
        body.addWidget(title)

        bits = [f"★ {_fmt_count(row.get('stars'))}"]
        stars_week = row.get("stars_week")
        if stars_week:
            color = UP_COLOR if stars_week > 0 else DOWN_COLOR
            bits[0] += f" <span style='color:{color}'>{stars_week:+d}</span>"
        if row.get("downloads_week") is not None:
            dl = f"↓ {_fmt_count(row['downloads_week'])}/wk"
            change = row.get("downloads_change")
            if change is not None:
                color = UP_COLOR if change >= 0 else DOWN_COLOR
                dl += f" <span style='color:{color}'>{'▲' if change >= 0 else '▼'}{abs(change) * 100:.0f}%</span>"
            bits.append(dl)
        if row.get("commits_4w") is not None:
            bits.append(f"{row['commits_4w']} commits/4wk")
        stats = QLabel(" · ".join(bits))
        stats.setWordWrap(True)
        stats.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        stats.setStyleSheet(f"color:{theme['muted']}; font-size:10.5px; background:transparent;")
        body.addWidget(stats)
        outer.addLayout(body, 1)

        spark = Sparkline(row.get("spark") or [], row.get("trend"))
        spark.setToolTip("weekly PyPI downloads" if row.get("spark_kind") == "downloads" else "weekly commits")
        outer.addWidget(spark, 0, Qt.AlignVCenter)

        self.setStyleSheet(f"QFrame#marketRow {{ background:{theme['card_bg']}; border-radius:10px; }}"
                           f"QFrame#marketRow:hover {{ background:{theme['btn_bg']}; }}")
        self.setCursor(Qt.PointingHandCursor)
        url = row.get("url", "")
        self.mousePressEvent = lambda ev: on_open(url)  # noqa: ARG005


PH_ORANGE = "#ff6154"


class ProductHuntRow(QFrame):
    """One Product Hunt launch under the Market board: thumbnail, name,
    tagline, upvotes, and a 'your field' tag when it mentions your terms.
    Product Hunt text is someone else's, so it's always plain text.
    Clicking opens the launch page."""

    def __init__(self, post: dict[str, Any], theme: dict[str, Any], on_open: Callable[[str], bool],
                 loader: "AvatarLoader | None" = None) -> None:
        super().__init__()
        self.setObjectName("phRow")
        self.slug = post.get("slug", "")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(8)
        outer.addWidget(_avatar_widget(post.get("name") or "?", post.get("thumbnail", ""), 26, loader))

        body = QVBoxLayout()
        body.setSpacing(1)
        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        name = QLabel(post.get("name", ""))
        name.setTextFormat(Qt.PlainText)
        name.setStyleSheet(f"color:{theme['text']}; font-size:11.5px; font-weight:700; background:transparent;")
        name_row.addWidget(name)
        if post.get("match"):
            tag = QLabel("your field")
            tag.setToolTip("Mentions " + ", ".join(post["match"][:4]))
            tag.setStyleSheet(f"color:{theme['text']}; background:{theme['section_btn']}; "
                              f"border-radius:7px; padding:1px 6px; font-size:9.5px;")
            tag.setFixedHeight(16)
            name_row.addWidget(tag)
        name_row.addStretch(1)
        body.addLayout(name_row)
        tagline = QLabel(post.get("tagline", ""))
        tagline.setTextFormat(Qt.PlainText)
        tagline.setWordWrap(True)
        tagline.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        tagline.setStyleSheet(f"color:{theme['muted']}; font-size:10.5px; background:transparent;")
        body.addWidget(tagline)
        outer.addLayout(body, 1)

        votes = QLabel(f"▲ {_fmt_count(post.get('votes'))}")
        votes.setToolTip(f"{post.get('votes', 0)} upvotes · {post.get('comments', 0)} comments")
        votes.setStyleSheet(f"color:{PH_ORANGE}; font-size:11px; font-weight:700; background:transparent;")
        outer.addWidget(votes, 0, Qt.AlignVCenter)

        self.setStyleSheet(f"QFrame#phRow {{ background:{theme['card_bg']}; border-radius:10px; }}"
                           f"QFrame#phRow:hover {{ background:{theme['btn_bg']}; }}")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(", ".join(post.get("topics") or []))
        url = post.get("url", "")
        self.mousePressEvent = lambda ev: on_open(url)  # noqa: ARG005


class _ClickableLabel(QLabel):
    """A word-wrapping label that acts like a link button."""

    def __init__(self, text: str, on_click: Callable[[], Any]) -> None:
        super().__init__(text)
        self._on_click = on_click
        self.setWordWrap(True)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802 -- Qt's own naming convention
        self._on_click()


class RepoCard(QFrame):
    """One `mygeeky contribute` result: repo, why it fits, and its best
    starter issues. Every click only opens a GitHub page -- forking and the
    PR are always left to the user."""

    def __init__(self, item: dict[str, Any], theme: dict[str, Any], on_open: Callable[[str], bool],
                 loader: "AvatarLoader | None" = None) -> None:
        super().__init__()
        self.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(_avatar_widget(item.get("owner", "?"), item.get("owner_avatar_url", ""), 32, loader))
        body = QVBoxLayout()
        body.setSpacing(2)
        title_row = QHBoxLayout()
        name_label = QLabel(item.get("full_name", ""))
        name_label.setStyleSheet("font-weight:600; font-size:12.5px; background:transparent;")
        name_label.setToolTip(item.get("full_name", ""))
        name_label.setMinimumWidth(1)  # a long owner/name is clipped instead of widening the card
        score = item.get("score")
        score_label = QLabel(f"{score:.2f}" if isinstance(score, (int, float)) else "")
        score_label.setStyleSheet(f"color:{theme['muted']}; font-size:12px; background:transparent;")
        title_row.addWidget(name_label, 1)
        title_row.addWidget(score_label)
        body.addLayout(title_row)

        meta = [f"★{item.get('stars', 0)}"]
        if item.get("language"):
            meta.insert(0, item["language"])
        meta_label = QLabel(" · ".join(meta))
        meta_label.setStyleSheet(f"color:{theme['muted']}; font-size:10.5px; background:transparent;")
        body.addWidget(meta_label)
        row.addLayout(body, 1)
        outer.addLayout(row)

        if item.get("description"):
            desc = QLabel(item["description"][:120])
            desc.setWordWrap(True)
            desc.setStyleSheet(f"color:{theme['muted']}; font-size:11px; background:transparent;")
            outer.addWidget(desc)
        if item.get("reasons"):
            why = QLabel("why: " + "; ".join(item["reasons"]))
            why.setWordWrap(True)
            why.setStyleSheet(f"color:{theme['accent']}; font-size:10.5px; background:transparent;")
            outer.addWidget(why)

        btn_style = (
            f"QPushButton {{ background:{theme['btn_bg']}; color:{theme['text']}; border:none; "
            f"border-radius:7px; padding:5px 8px; font-size:11px; text-align:left; }}"
            f"QPushButton:hover {{ background:{theme['btn_hover']}; }}"
        )
        for issue in (item.get("starter_issues") or [])[:2]:
            title = issue.get("title") or ""
            # a wrapping label, not a QPushButton: button text never wraps, so a
            # long issue title would force the card wider than the panel
            issue_row = _ClickableLabel("→ " + (title[:97] + "…" if len(title) > 100 else title),
                                        lambda u=issue.get("url", ""): on_open(u))
            issue_row.setObjectName("issue")
            issue_row.setToolTip(title)
            issue_row.setStyleSheet(
                f"#issue {{ background:{theme['btn_bg']}; color:{theme['text']}; border-radius:7px; "
                f"padding:5px 8px; font-size:11px; }}"
                f"#issue:hover {{ background:{theme['btn_hover']}; }}"
            )
            outer.addWidget(issue_row)

        repo_url = item.get("repo_url", "")
        actions = QHBoxLayout()
        actions.addStretch(1)
        for label, url in (("Fork →", item.get("fork_url", "")), ("Open →", repo_url)):
            btn = QPushButton(label)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(btn_style)
            btn.clicked.connect(lambda checked=False, u=url: on_open(u))
            actions.addWidget(btn)
        outer.addLayout(actions)

        self.setStyleSheet(f"#card {{ background:{theme['card_bg']}; border-radius:10px; }}")
        # Clicking the card body opens the repo; the issue/Fork/Open buttons
        # consume their own clicks first, so no double-trigger.
        self.setCursor(Qt.PointingHandCursor)
        self.mousePressEvent = lambda ev: on_open(repo_url)  # noqa: ARG005


class SpotlightCard(QFrame):
    """One slide in the Live tab's ticker: a photo + headline + detail,
    normalized from either an activity event or a suggestion (see
    MyGeekyPanel._build_spotlight_items)."""

    KIND_BADGES = {"activity": "LIVE", "suggestion": "SUGGESTED", "signal": "FOR YOU"}

    def __init__(self, item: dict[str, Any], theme: dict[str, Any],
                 on_open: Callable[[str], bool], loader: "AvatarLoader | None") -> None:
        super().__init__()
        self.setObjectName("card")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(10)
        row.addWidget(_avatar_widget(item.get("username", "?"), item.get("avatar_url", ""), 40, loader))

        body = QVBoxLayout()
        body.setSpacing(1)
        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        badge = QLabel(self.KIND_BADGES.get(item.get("kind"), ""))
        badge.setStyleSheet(
            f"color:{theme['accent']}; font-size:9px; font-weight:800; letter-spacing:0.6px; background:transparent;"
        )
        name_label = QLabel(item.get("username", ""))
        name_label.setStyleSheet("font-weight:700; font-size:12.5px; background:transparent;")
        top_row.addWidget(badge)
        top_row.addWidget(name_label)
        top_row.addStretch(1)
        if item.get("time_text"):
            time_label = QLabel(item["time_text"])
            time_label.setStyleSheet(f"color:{theme['muted']}; font-size:10px; background:transparent;")
            top_row.addWidget(time_label)
        body.addLayout(top_row)

        headline = QLabel(item.get("headline", ""))
        headline.setWordWrap(True)
        headline.setStyleSheet(f"color:{theme['text']}; font-size:11.5px; background:transparent;")
        body.addWidget(headline)

        if item.get("detail"):
            detail = QLabel(item["detail"])
            detail.setWordWrap(True)
            detail.setStyleSheet(f"color:{theme['muted']}; font-size:10.5px; background:transparent;")
            body.addWidget(detail)

        row.addLayout(body, 1)
        self.setStyleSheet(f"#card {{ background:{theme['card_bg']}; border-radius:12px; }}")
        self.setCursor(Qt.PointingHandCursor)
        profile_url = item.get("profile_url", "")
        self.mousePressEvent = lambda ev: on_open(profile_url)  # noqa: ARG005


class SpotlightTicker(QWidget):
    """A vertical news-feed strip: as many cards as the available height
    fits, stacked and all visible at once, scrolling up together on a
    timer -- the newest story rises in at the bottom while the oldest
    visible one scrolls off the top. Fills whatever space its parent
    layout gives it (see `_build_live_tab`'s stretch factor) rather than
    a fixed one-card height, so a taller panel shows more stories at once."""

    CARD_HEIGHT = 72
    CARD_SPACING = 8

    def __init__(self, on_open: Callable[[str], bool], loader: "AvatarLoader | None") -> None:
        super().__init__()
        self._on_open = on_open
        self._loader = loader
        self._theme: dict[str, Any] = THEMES["midnight"]
        self._items: list[dict[str, Any]] = []
        self._next_index = 0
        self._cards: list[SpotlightCard] = []
        self._anim_group: QParallelAnimationGroup | None = None
        self.setMinimumHeight(self.CARD_HEIGHT)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)

    def _visible_count(self) -> int:
        step = self.CARD_HEIGHT + self.CARD_SPACING
        return max(1, (self.height() + self.CARD_SPACING) // step)

    def _slot_y(self, slot: int) -> int:
        return slot * (self.CARD_HEIGHT + self.CARD_SPACING)

    def _make_card(self, item: dict[str, Any]) -> SpotlightCard:
        card = SpotlightCard(item, self._theme, self._on_open, self._loader)
        card.setParent(self)
        return card

    def set_theme(self, theme: dict[str, Any]) -> None:
        self._theme = theme
        if self._items:
            self._fill()

    def set_items(self, items: list[dict[str, Any]]) -> None:
        self._items = items
        self._fill()

    def _fill(self) -> None:
        """(Re)populate every visible slot from scratch -- first load,
        theme change, and any resize (the slot count depends on height)."""
        for card in self._cards:
            card.hide()  # deleteLater only runs on a later event-loop turn
            card.deleteLater()
        self._cards = []
        if not self._items:
            return
        count = min(self._visible_count(), len(self._items))
        for slot in range(count):
            card = self._make_card(self._items[slot % len(self._items)])
            card.setGeometry(0, self._slot_y(slot), self.width(), self.CARD_HEIGHT)
            card.show()
            self._cards.append(card)
        self._next_index = count % len(self._items)

    def start(self, interval_ms: int) -> None:
        if len(self._items) > len(self._cards):
            self._timer.start(max(1200, interval_ms))
        else:
            self._timer.stop()

    def stop(self) -> None:
        self._timer.stop()

    def is_running(self) -> bool:
        return self._timer.isActive()

    def _advance(self) -> None:
        if not self._cards or len(self._items) <= len(self._cards):
            return

        departing = self._cards.pop(0)
        visible_n = len(self._cards) + 1  # slot count before this update

        incoming = self._make_card(self._items[self._next_index])
        self._next_index = (self._next_index + 1) % len(self._items)
        incoming.setGeometry(0, self._slot_y(visible_n), self.width(), self.CARD_HEIGHT)
        incoming.show()
        self._cards.append(incoming)

        group = QParallelAnimationGroup(self)

        anim_out = QPropertyAnimation(departing, b"pos", self)
        anim_out.setDuration(420)
        anim_out.setStartValue(departing.pos())
        anim_out.setEndValue(QPoint(0, -self.CARD_HEIGHT))
        anim_out.setEasingCurve(QEasingCurve.OutCubic)
        group.addAnimation(anim_out)

        for slot, card in enumerate(self._cards):
            anim = QPropertyAnimation(card, b"pos", self)
            anim.setDuration(420)
            anim.setStartValue(card.pos())
            anim.setEndValue(QPoint(0, self._slot_y(slot)))
            anim.setEasingCurve(QEasingCurve.OutCubic)
            group.addAnimation(anim)

        group.finished.connect(departing.deleteLater)
        self._anim_group = group  # keep a reference alive until it finishes
        group.start()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._items:
            self._fill()


_RGBA_RE = re.compile(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)")
_GRADIENT_STOP_RE = re.compile(r"stop:\s*([\d.]+)\s+((?:rgba?\([^)]*\))|#[0-9a-fA-F]{3,8})")


def _parse_color(spec: str, force_alpha: int | None = None) -> QColor:
    """THEMES colors are Qt-stylesheet strings, e.g. 'rgba(255,255,255,31)'
    (Qt's rgba() alpha is 0-255, not the 0-1 the CSS spec uses elsewhere) --
    QColor's own string constructor doesn't understand rgba(), only
    #rrggbb/#aarrggbb and SVG color names, so it has to be hand-parsed.

    force_alpha overrides whatever alpha the spec itself carries -- used to
    paint the outer panel fully opaque regardless of the theme's own baked-in
    glass alpha, so the Transparency slider (a plain setWindowOpacity
    multiplier) has real headroom: multiplying can only ever *reduce*
    opacity below what's painted, never raise it, so at 0% the content
    itself must already be fully solid or the slider could never reach it."""
    match = _RGBA_RE.match(spec.strip())
    if match:
        r, g, b = (int(float(match.group(i))) for i in (1, 2, 3))
        a = force_alpha if force_alpha is not None else (
            int(float(match.group(4))) if match.group(4) is not None else 255
        )
        return QColor(r, g, b, a)
    color = QColor(spec)
    if force_alpha is not None:
        color.setAlpha(force_alpha)
    return color


def _parse_bg_brush(spec: str, rect: QRectF, force_alpha: int | None = None) -> QBrush:
    """theme['bg'] is a Qt-stylesheet qlineargradient(...) string (shared with
    the QSS `background:` rule used elsewhere in this file). QColor can't
    read that either -- passing it straight through silently produced solid
    opaque black instead of the intended translucent glass gradient."""
    stops = _GRADIENT_STOP_RE.findall(spec)
    if not stops:
        return QBrush(_parse_color(spec, force_alpha))
    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    for pos, color in stops:
        gradient.setColorAt(float(pos), _parse_color(color, force_alpha))
    return QBrush(gradient)


class RoundedPanel(QFrame):
    """A frameless-window background frame with genuinely curved corners.

    A stylesheet `border-radius` on a frame sitting directly on top of a
    WA_TranslucentBackground top-level window doesn't reliably zero out the
    alpha channel in the corner pixels on this Windows/Qt/DWM combination --
    they render opaque-square instead of see-through-rounded. Painting the
    shape by hand, explicitly clearing to transparent first, sidesteps that.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bg_spec = ""
        self._border_spec = ""
        self._radius = 0.0

    def set_style(self, bg: str, border: str, radius: float) -> None:
        self._bg_spec = bg
        self._border_spec = border
        self._radius = radius
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt's own naming convention
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        # Painted fully opaque regardless of the theme's own glass alpha --
        # the window-level Transparency slider (setWindowOpacity) is the only
        # thing that should make this see-through; see _parse_color.
        painter.fillPath(path, _parse_bg_brush(self._bg_spec, rect, force_alpha=255))
        painter.setPen(QPen(_parse_color(self._border_spec, force_alpha=255), 1))
        painter.drawPath(path)
        painter.end()


HEART_COLORS = ("#ff6fa8", "#ff8fc0", "#ff5c8a", "#ffa3c9", "#e86fd8")


def _heart_path(size: float) -> QPainterPath:
    """A heart `size` wide, centred on (0, 0)."""
    s = size / 2.0
    path = QPainterPath(QPointF(0, s * 0.95))
    path.cubicTo(-s * 1.3, s * 0.05, -s * 0.75, -s * 1.15, 0, -s * 0.45)
    path.cubicTo(s * 0.75, -s * 1.15, s * 1.3, s * 0.05, 0, s * 0.95)
    return path


class HeartsOverlay(QWidget):
    """A see-through, click-through window above the folded icon that lets a
    few small hearts drift up like smoke: each rises, wobbles, shrinks and
    fades out within a few seconds. It's only on screen during a puff, so
    there's nothing to click by accident and nothing ticking in between."""

    W, H = 120, 190

    def __init__(self) -> None:
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFixedSize(self.W, self.H)
        self._particles: list[dict[str, float]] = []
        self._clock = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    def is_active(self) -> bool:
        return bool(self._particles)

    def puff(self, icon_rect, dock_side: str, count: int = 4) -> None:
        """Release `count` hearts from the top of `icon_rect` (global coords),
        drifting away from the screen edge the panel is docked to."""
        import random
        inward = -1.0 if dock_side != "left" else 1.0
        x = icon_rect.center().x() - self.W // 2 + int(inward * 18)
        self.move(x, icon_rect.top() - self.H + icon_rect.height() // 3)
        for i in range(count):
            self._particles.append({
                "born": self._clock + i * random.uniform(0.35, 0.6),
                "life": random.uniform(2.6, 3.6),
                "x0": self.W / 2 + random.uniform(-8, 8) - inward * 18,
                "drift": inward * random.uniform(8, 26),
                "size": random.uniform(9, 14),
                "phase": random.uniform(0, math.tau),
                "color": random.randrange(len(HEART_COLORS)),
            })
        if not self.isVisible():
            self.show()
        self._timer.start()

    def _tick(self) -> None:
        self._clock += self._timer.interval() / 1000.0
        self._particles = [p for p in self._particles if self._clock - p["born"] < p["life"]]
        if not self._particles:
            self._timer.stop()
            self._clock = 0.0
            self.hide()
            return
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt's own naming convention
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.setPen(Qt.NoPen)
        for p in self._particles:
            age = self._clock - p["born"]
            if age < 0:
                continue
            t = age / p["life"]
            ease = 1 - (1 - t) ** 2                     # quick start, slow drift at the end
            x = p["x0"] + p["drift"] * ease + math.sin(p["phase"] + t * 7) * 5 * (1 - t)
            y = self.H - 8 - ease * (self.H - 30)
            size = p["size"] * (1 - 0.65 * t)            # shrinks as it rises
            fade_in = min(1.0, age / 0.25)
            alpha = int(215 * fade_in * (1 - t) ** 1.4)
            color = QColor(HEART_COLORS[int(p["color"])])
            halo = QRadialGradient(QPointF(x, y), size * 1.4)   # a soft, smoky glow
            glow = QColor(color)
            glow.setAlpha(alpha // 4)
            halo.setColorAt(0.0, glow)
            glow.setAlpha(0)
            halo.setColorAt(1.0, glow)
            painter.setBrush(QBrush(halo))
            painter.drawEllipse(QPointF(x, y), size * 1.4, size * 1.4)
            color.setAlpha(alpha)
            painter.setBrush(color)
            painter.save()
            painter.translate(x, y)
            painter.rotate(math.sin(p["phase"] + t * 5) * 12)
            painter.drawPath(_heart_path(size))
            painter.restore()
        painter.end()


class RoundedButton(QPushButton):
    """A pill-shaped button with hand-painted, always-transparent corners.

    Same rationale as RoundedPanel -- used for the folded/collapsed state
    of the panel, which is just this one button standing in for the whole
    window.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._bg_spec = ""
        self._border_spec = ""
        self._text_color = QColor("#ffffff")
        self._radius = 18.0
        self._icon: QPixmap | None = None

    def set_icon(self, pixmap: QPixmap) -> None:
        """Icon-only mode: just the icon, filling the button, no pill behind it."""
        self._icon = pixmap
        self.update()

    def set_style(self, bg: str, border: str, text_color: str, radius: float = 18.0) -> None:
        self._bg_spec = bg
        self._border_spec = border
        self._text_color = QColor(text_color)
        self._radius = radius
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt's own naming convention
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self._icon is not None and not self._icon.isNull():
            side = int(min(rect.width(), rect.height()))
            icon = self._icon.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter.drawPixmap(int(rect.center().x() - icon.width() / 2),
                               int(rect.center().y() - icon.height() / 2), icon)
            painter.end()
            return
        # This button doubles as the folded state: a narrow, full-height strip
        # docked to the screen edge, not a compact pill -- so the radius is a
        # small fixed value, never proportional to the (tall) widget height.
        radius = min(self._radius, rect.width() / 2.0, rect.height() / 2.0)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        # Painted fully opaque for the same reason as RoundedPanel -- the
        # window-level Transparency slider needs real headroom above 0%.
        painter.fillPath(path, _parse_bg_brush(self._bg_spec, rect, force_alpha=255))
        painter.setPen(QPen(_parse_color(self._border_spec, force_alpha=255), 1))
        painter.drawPath(path)

        painter.setPen(self._text_color)
        painter.setFont(self.font())
        painter.drawText(rect, Qt.AlignCenter, self.text())
        painter.end()


class MyGeekyPanel(QWidget):
    def __init__(self, cfg: MyGeekyConfig) -> None:
        super().__init__()
        self.cfg = cfg
        self.active_tab = "live"
        self._workers: list[_Worker] = []
        self.avatar_loader = AvatarLoader()
        self._last_activity_events: list[dict[str, Any]] = []
        self._expanded_actors: set[str] = set()  # kept across refreshes
        self._last_suggestions: list[dict[str, Any]] = []
        self._contrib_running = False
        self._market_running = False
        self._sugg_running = False
        self._signals_running = False
        self._last_incoming: list[dict[str, Any]] = []

        self.setWindowTitle("myGeeKy")
        if ICON_WINDOW.exists():
            self.setWindowIcon(QIcon(str(ICON_WINDOW)))
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        # Blanket transparent default for every descendant widget -- QScrollArea's
        # internal viewport in particular paints an opaque background by default
        # in Qt regardless of the top-level window's own translucency, which
        # would otherwise cover most of the panel (it hosts the Suggestions and
        # Activity tabs). #panel/the folded tab button set their own background
        # explicitly (below) and, being more specific selectors, still win.
        self.setStyleSheet("QWidget { background: transparent; }")

        self._build_ui()
        self._apply_theme()
        self._dock(folded=False)

        self._load_status()
        self._load_live_stats()
        self._load_suggestions()
        self._load_contributions()
        self._refresh_activity(force=False)
        self._load_model_history()
        self._load_market()
        self._refresh_signals(force=False)
        self.ticker.start(int(self.cfg.gui_live_rotate_seconds * 1000))

        self._activity_timer = QTimer(self)
        self._activity_timer.timeout.connect(lambda: self._refresh_activity(force=False))
        self._activity_timer.start(60_000)

        # every 10 minutes (and once now): search again if the list ran empty
        # and the last search is old enough -- see suggestions_auto_refresh_due
        # the board snapshots once a day; check hourly (and once now) whether it's due
        self._market_timer = QTimer(self)
        self._market_timer.timeout.connect(self._maybe_refresh_market)
        self._market_timer.start(60 * 60_000)
        QTimer.singleShot(20_000, self._maybe_refresh_market)

        # re-reads beacons only once beacon_refresh_minutes have passed
        self._signals_timer = QTimer(self)
        self._signals_timer.timeout.connect(lambda: self._refresh_signals(force=False))
        self._signals_timer.start(5 * 60_000)

        self.hearts = HeartsOverlay()
        self._hearts_timer = QTimer(self)
        self._hearts_timer.timeout.connect(self._maybe_puff_hearts)
        self._hearts_timer.start(max(30_000, int(self.cfg.gui_hearts_interval_minutes * 60_000)))

        # a newer myGeeKy on PyPI? (PyPI is asked at most once a day; see updates.py)
        self._update_info: dict[str, Any] = {}
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._check_for_update)
        self._update_timer.start(6 * 60 * 60_000)
        QTimer.singleShot(8_000, self._check_for_update)

        self._sugg_timer = QTimer(self)
        self._sugg_timer.timeout.connect(self._maybe_auto_refresh_suggestions)
        self._sugg_timer.start(10 * 60_000)
        QTimer.singleShot(5_000, self._maybe_auto_refresh_suggestions)

    # ------------------------------------------------------------------ UI construction
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Folded tab and full panel are siblings shown one at a time (not a
        # QStackedWidget: a stack is never smaller than its LARGEST page, so the
        # "folded" window could never actually get narrow).
        self.folded_widget = RoundedButton("")
        if ICON_FOLDED.exists():
            self.folded_widget.set_icon(QPixmap(str(ICON_FOLDED)))
        self.folded_widget.setToolTip("myGeeKy — click to open")
        self.folded_widget.setCursor(Qt.PointingHandCursor)
        self.folded_widget.setMinimumSize(1, 1)
        self.folded_widget.clicked.connect(self.unfold)
        self.folded_widget.installEventFilter(self)  # hover -> fully opaque
        outer.addWidget(self.folded_widget)

        self.panel_frame = RoundedPanel()
        self.panel_frame.setObjectName("panel")
        panel_layout = QVBoxLayout(self.panel_frame)
        panel_layout.setContentsMargins(16, 14, 16, 16)
        panel_layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(6)
        if ICON_HEADER.exists():
            icon_label = QLabel()
            icon_label.setPixmap(QPixmap(str(ICON_HEADER)))
            icon_label.setFixedSize(20, 20)
            icon_label.setScaledContents(True)
            header.addWidget(icon_label)
        logo = QLabel("myGeeKy")
        logo.setStyleSheet("font-weight:700; font-size:15px; background:transparent;")
        header.addWidget(logo)
        header.addStretch(1)

        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setFixedSize(26, 26)
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.setToolTip("Settings — theme & transparency")
        self.settings_btn.clicked.connect(self._toggle_settings)
        header.addWidget(self.settings_btn)

        self.fold_btn = QPushButton("⟩")
        self.fold_btn.setFixedSize(26, 26)
        self.fold_btn.setCursor(Qt.PointingHandCursor)
        self.fold_btn.clicked.connect(self.fold)
        header.addWidget(self.fold_btn)
        panel_layout.addLayout(header)

        self.settings_panel = self._build_settings_panel()
        self.settings_panel.setVisible(False)
        panel_layout.addWidget(self.settings_panel)

        self.update_banner = self._build_update_banner()
        self.update_banner.setVisible(False)
        panel_layout.addWidget(self.update_banner)

        self.status_label = QLabel("Loading…")
        self.status_label.setWordWrap(True)
        panel_layout.addWidget(self.status_label)

        tabs_row = QHBoxLayout()
        self.tab_buttons: dict[str, QPushButton] = {}
        for name, label in (("live", "Live"), ("suggestions", "Suggestions"), ("repos", "Repos"),
                             ("market", "Market"), ("activity", "Activity"), ("signals", "Signals"),
                             ("model", "Model")):
            btn = QPushButton(label)
            # Qt's Windows style gives every push button a ~75px minimum width;
            # five of those made the panel wider than gui_expanded_width.
            btn.setMinimumWidth(1)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, n=name: self._switch_tab(n))
            self.tab_buttons[name] = btn
            # width follows the label, so six tabs still fit the narrow panel
            tabs_row.addWidget(btn, len(label) + 3)
        panel_layout.addLayout(tabs_row)

        self.content_stack = QStackedWidget()
        panel_layout.addWidget(self.content_stack, 1)

        self._tab_order = ["live", "suggestions", "repos", "market", "activity", "signals", "model"]
        self.content_stack.addWidget(self._build_live_tab())
        self.content_stack.addWidget(self._build_suggestions_tab())
        self.content_stack.addWidget(self._build_repos_tab())
        self.content_stack.addWidget(self._build_market_tab())
        self.content_stack.addWidget(self._build_activity_tab())
        self.content_stack.addWidget(self._build_signals_tab())
        self.content_stack.addWidget(self._build_model_tab())

        outer.addWidget(self.panel_frame)
        self.folded_widget.hide()

    def _build_live_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(8)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)
        self.stat_friends_label = QLabel("—")
        self.stat_new_label = QLabel("—")
        self.stat_rate_label = QLabel("—")
        for lbl in (self.stat_friends_label, self.stat_new_label, self.stat_rate_label):
            lbl.setStyleSheet("font-size:11px; font-weight:600; background:transparent;")
            stats_row.addWidget(lbl)
        stats_row.addStretch(1)
        layout.addLayout(stats_row)

        self.ticker = SpotlightTicker(self._on_ticker_clicked, self.avatar_loader)
        layout.addWidget(self.ticker, 1)

        hint = QLabel("Recent activity and top suggestions, scrolling live — click a card to open the profile.")
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size:10px; background:transparent;")
        layout.addWidget(hint)
        return page

    def _build_suggestions_tab(self) -> QScrollArea:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)

        actions_row = QHBoxLayout()
        hint = QLabel("Click someone to open their profile — they then leave this list. You follow manually.")
        hint.setWordWrap(True)
        self.refresh_sugg_btn = QPushButton("Refresh")
        self.refresh_sugg_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_sugg_btn.clicked.connect(self._on_refresh_suggestions)
        actions_row.addWidget(hint, 1)
        actions_row.addWidget(self.refresh_sugg_btn)
        layout.addLayout(actions_row)

        fb_header = QLabel("LIKELY TO FOLLOW BACK")
        fb_header.setStyleSheet("font-size:10.5px; font-weight:700; letter-spacing:0.5px; background:transparent;")
        layout.addWidget(fb_header)
        followback_container = QWidget()
        self.followback_area = QVBoxLayout(followback_container)
        self.followback_area.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(followback_container)

        dm_header = QLabel("DOMAIN-FIT HIGHLIGHTS")
        dm_header.setStyleSheet(
            "font-size:10.5px; font-weight:700; letter-spacing:0.5px; margin-top:8px; background:transparent;"
        )
        layout.addWidget(dm_header)
        domain_container = QWidget()
        self.domain_area = QVBoxLayout(domain_container)
        self.domain_area.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(domain_container)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background:transparent; border:none;")
        # QScrollArea's viewport paints an opaque background by default in
        # Qt, independent of the top-level window's translucency or any
        # stylesheet on the QScrollArea widget itself -- this is what was
        # actually covering most of the panel.
        scroll.viewport().setAutoFillBackground(False)
        scroll.viewport().setStyleSheet("background: transparent;")
        page.setAutoFillBackground(False)
        return scroll

    def _build_repos_tab(self) -> QScrollArea:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)

        actions_row = QHBoxLayout()
        hint = QLabel("Repos you could improve — fork and send the PR yourself.")
        hint.setWordWrap(True)
        self.refresh_repos_btn = QPushButton("Refresh")
        self.refresh_repos_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_repos_btn.clicked.connect(self._on_refresh_contributions)
        actions_row.addWidget(hint, 1)
        actions_row.addWidget(self.refresh_repos_btn)
        layout.addLayout(actions_row)

        repos_container = QWidget()
        self.repos_area = QVBoxLayout(repos_container)
        self.repos_area.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(repos_container)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background:transparent; border:none;")
        # Same opaque-viewport workaround as the Suggestions tab.
        scroll.viewport().setAutoFillBackground(False)
        scroll.viewport().setStyleSheet("background: transparent;")
        page.setAutoFillBackground(False)
        return scroll

    def _build_market_tab(self) -> QScrollArea:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 4, 0)

        actions_row = QHBoxLayout()
        self.market_updated_label = QLabel("")
        self.refresh_market_btn = QPushButton("Refresh")
        self.refresh_market_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_market_btn.clicked.connect(lambda: self._refresh_market(force=True))
        actions_row.addWidget(self.market_updated_label, 1)
        actions_row.addWidget(self.refresh_market_btn)
        layout.addLayout(actions_row)
        self.market_hint = QLabel("The popular, active repos in your field, ranked by momentum: stars gained, "
                                  "commits and PyPI downloads. ▲▼ = places moved since the last day ranked.")
        self.market_hint.setWordWrap(True)
        layout.addWidget(self.market_hint)

        market_container = QWidget()
        self.market_area = QVBoxLayout(market_container)
        self.market_area.setContentsMargins(0, 0, 0, 0)
        self.market_area.setSpacing(6)
        layout.addWidget(market_container)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background:transparent; border:none;")
        scroll.viewport().setAutoFillBackground(False)
        page.setAutoFillBackground(False)
        return scroll

    def _build_activity_tab(self) -> QScrollArea:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)

        actions_row = QHBoxLayout()
        self.activity_updated_label = QLabel("")
        self.refresh_act_btn = QPushButton("Refresh")
        self.refresh_act_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_act_btn.clicked.connect(lambda: self._refresh_activity(force=True))
        actions_row.addWidget(self.activity_updated_label, 1)
        actions_row.addWidget(self.refresh_act_btn)
        layout.addLayout(actions_row)

        activity_container = QWidget()
        self.activity_area = QVBoxLayout(activity_container)
        self.activity_area.setContentsMargins(0, 0, 0, 0)
        self.activity_area.setSpacing(6)
        layout.addWidget(activity_container)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background:transparent; border:none;")
        # QScrollArea's viewport paints an opaque background by default in
        # Qt, independent of the top-level window's translucency or any
        # stylesheet on the QScrollArea widget itself -- this is what was
        # actually covering most of the panel.
        scroll.viewport().setAutoFillBackground(False)
        scroll.viewport().setStyleSheet("background: transparent;")
        page.setAutoFillBackground(False)
        return scroll

    def _build_signals_tab(self) -> QScrollArea:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)

        actions_row = QHBoxLayout()
        self.signals_updated_label = QLabel("")
        self.refresh_signals_btn = QPushButton("Refresh")
        self.refresh_signals_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_signals_btn.clicked.connect(lambda: self._refresh_signals(force=True))
        actions_row.addWidget(self.signals_updated_label, 1)
        actions_row.addWidget(self.refresh_signals_btn)
        layout.addLayout(actions_row)
        self.signals_hint = QLabel("")
        self.signals_hint.setWordWrap(True)
        layout.addWidget(self.signals_hint)

        signals_container = QWidget()
        self.signals_area = QVBoxLayout(signals_container)
        self.signals_area.setContentsMargins(0, 0, 0, 0)
        self.signals_area.setSpacing(6)
        layout.addWidget(signals_container)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background:transparent; border:none;")
        # Same opaque-viewport workaround as the Suggestions tab.
        scroll.viewport().setAutoFillBackground(False)
        scroll.viewport().setStyleSheet("background: transparent;")
        page.setAutoFillBackground(False)
        return scroll

    def _build_update_banner(self) -> QFrame:
        banner = QFrame()
        banner.setObjectName("updateBanner")
        layout = QVBoxLayout(banner)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        self.update_label = QLabel("")
        self.update_label.setWordWrap(True)
        layout.addWidget(self.update_label)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.update_btn = QPushButton("Update")
        self.update_btn.setObjectName("updateNow")
        self.update_btn.setCursor(Qt.PointingHandCursor)
        self.update_btn.clicked.connect(self._on_update_clicked)
        self.whats_new_btn = QPushButton("What's new")
        self.whats_new_btn.setCursor(Qt.PointingHandCursor)
        self.whats_new_btn.clicked.connect(
            lambda: logic.open_link(self._update_info.get("releases_url", "")))
        self.later_btn = QPushButton("Later")
        self.later_btn.setCursor(Qt.PointingHandCursor)
        self.later_btn.clicked.connect(self._on_update_later)
        for b in (self.update_btn, self.whats_new_btn, self.later_btn):
            row.addWidget(b)
        row.addStretch(1)
        layout.addLayout(row)
        return banner

    def _check_for_update(self) -> None:
        self._run_async(lambda: logic.get_update_info(self.cfg), self._on_update_info)

    def _on_update_info(self, info: Any) -> None:
        info = info if isinstance(info, dict) else {}
        self._update_info = info
        if not info.get("show"):
            self.update_banner.setVisible(False)
            return
        if info.get("editable"):
            self.update_label.setText(f"✨ myGeeKy {info['latest']} is out. This is a developer install, "
                                      "so update it with git pull.")
            self.update_btn.setVisible(False)
        else:
            self.update_label.setText(f"✨ myGeeKy {info['latest']} is available (you have {info['current']}).")
            self.update_btn.setVisible(True)
        self.update_banner.setVisible(True)

    def _on_update_later(self) -> None:
        if self._update_info.get("latest"):
            logic.dismiss_update(self.cfg, self._update_info["latest"])
        self.update_banner.setVisible(False)

    def _on_update_clicked(self) -> None:
        for b in (self.update_btn, self.later_btn):
            b.setEnabled(False)
        self.update_label.setText("Updating myGeeKy… (about a minute; keep using it meanwhile)")
        self._run_async(logic.install_update, self._on_update_done)

    def _on_update_done(self, result: Any) -> None:
        result = result if isinstance(result, dict) else {"ok": False, "message": str(result)}
        if result.get("ok"):
            self.update_label.setText(f"✓ {result['message']} Restarting…")
            from .. import updates
            updates.relaunch_panel_after_exit()
            QTimer.singleShot(600, QApplication.instance().quit)
            return
        self.update_label.setText(f"Couldn't update: {result.get('message', 'unknown error')}")
        self.update_btn.setText("Try again")
        for b in (self.update_btn, self.later_btn):
            b.setEnabled(True)

    def _build_settings_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("settings")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        theme_row = QHBoxLayout()
        theme_label = QLabel("Theme")
        theme_label.setStyleSheet("font-size:11px; font-weight:600; background:transparent;")
        theme_row.addWidget(theme_label)
        theme_row.addStretch(1)
        self.swatch_buttons: dict[str, QPushButton] = {}
        for name in ("aurora", "midnight", "frosted"):
            btn = QPushButton()
            btn.setFixedSize(17, 17)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(name.capitalize())
            btn.clicked.connect(lambda checked=False, n=name: self._on_theme_clicked(n))
            self.swatch_buttons[name] = btn
            theme_row.addWidget(btn)
        layout.addLayout(theme_row)

        opacity_row = QHBoxLayout()
        opacity_label = QLabel("Transparency")
        opacity_label.setStyleSheet("font-size:11px; font-weight:600; background:transparent;")
        self.opacity_value_label = QLabel("")
        self.opacity_value_label.setStyleSheet("font-size:10.5px; background:transparent;")
        opacity_row.addWidget(opacity_label)
        opacity_row.addStretch(1)
        opacity_row.addWidget(self.opacity_value_label)
        layout.addLayout(opacity_row)

        # The slider reads as "Transparency": 0 = no transparency (fully
        # opaque) .. 100 = full transparency (invisible). That's the inverse
        # of Qt's own windowOpacity (1.0 = opaque, 0.0 = invisible), so the
        # slider's own range is always a plain 0-100 regardless of the
        # opacity bounds in app.py -- see _slider_to_opacity/_opacity_to_slider.
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setCursor(Qt.PointingHandCursor)
        self.opacity_slider.setValue(self._opacity_to_slider(self.cfg.gui_opacity))
        self.opacity_slider.valueChanged.connect(self._on_opacity_preview)
        self.opacity_slider.sliderReleased.connect(self._on_opacity_committed)
        layout.addWidget(self.opacity_slider)

        self.hearts_check = QCheckBox("Floating hearts on the folded icon")
        self.hearts_check.setCursor(Qt.PointingHandCursor)
        self.hearts_check.setChecked(self.cfg.gui_hearts_enabled)
        self.hearts_check.toggled.connect(self._on_hearts_toggled)
        layout.addWidget(self.hearts_check)

        return panel

    def _on_hearts_toggled(self, enabled: bool) -> None:
        logic.set_hearts(self.cfg, enabled)
        if enabled and self.folded_widget.isVisible():
            self._puff_hearts()  # show what you just turned on

    def _maybe_puff_hearts(self) -> None:
        if self.cfg.gui_hearts_enabled and self.folded_widget.isVisible() and self.isVisible():
            self._puff_hearts()

    def _puff_hearts(self) -> None:
        from PySide6.QtCore import QRect
        top_left = self.folded_widget.mapToGlobal(QPoint(0, 0))
        self.hearts.puff(QRect(top_left, self.folded_widget.size()), self.cfg.gui_dock_side)

    def _toggle_settings(self) -> None:
        self.settings_panel.setVisible(not self.settings_panel.isVisible())

    @staticmethod
    def _slider_to_opacity(value: int) -> float:
        return 1.0 - (value / 100.0)

    @staticmethod
    def _opacity_to_slider(opacity: float) -> int:
        return int(round((1.0 - opacity) * 100))

    def _on_opacity_preview(self, value: int) -> None:
        """Applied live while dragging -- only persisted on release
        (_on_opacity_committed) so we're not hitting disk on every tick."""
        self.setWindowOpacity(self._slider_to_opacity(value))
        self.opacity_value_label.setText(f"{value}%")

    def _on_opacity_committed(self) -> None:
        logic.set_opacity(self.cfg, self._slider_to_opacity(self.opacity_slider.value()))

    def _build_model_tab(self) -> QScrollArea:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 4, 4)
        layout.setSpacing(10)

        hero = QHBoxLayout()
        hero.setSpacing(12)
        self.auc_gauge = AucGauge()
        hero.addWidget(self.auc_gauge)
        verdict_box = QVBoxLayout()
        verdict_box.setSpacing(4)
        verdict_box.addStretch(1)
        self.model_grade_label = QLabel("")
        self.model_summary_label = QLabel("Loading…")
        self.model_summary_label.setWordWrap(True)
        self.model_delta_label = QLabel("")
        for label in (self.model_grade_label, self.model_summary_label, self.model_delta_label):
            verdict_box.addWidget(label)
        verdict_box.addStretch(1)
        hero.addLayout(verdict_box, 1)
        layout.addLayout(hero)

        tiles = QHBoxLayout()
        tiles.setSpacing(6)
        self.model_tiles = {key: StatTile(caption) for key, caption in (
            ("examples", "examples"), ("positives", "follow-backs"),
            ("rate", "follow-back rate"), ("retrains", "retrains"))}
        for tile in self.model_tiles.values():
            tiles.addWidget(tile, 1)
        layout.addLayout(tiles)

        self.model_section_labels = [QLabel("WHAT IT HAS LEARNED"), QLabel("GETTING SHARPER?")]
        layout.addWidget(self.model_section_labels[0])
        self.weight_bars = WeightBars()
        layout.addWidget(self.weight_bars)
        self.weights_hint = QLabel("Right = makes a follow-back more likely; left = less likely.")
        self.weights_hint.setWordWrap(True)
        layout.addWidget(self.weights_hint)

        layout.addWidget(self.model_section_labels[1])
        self.chart = TrendChart()
        layout.addWidget(self.chart)
        self.model_footer_label = QLabel("")
        self.model_footer_label.setWordWrap(True)
        layout.addWidget(self.model_footer_label)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background:transparent; border:none;")
        scroll.viewport().setAutoFillBackground(False)
        page.setAutoFillBackground(False)
        return scroll

    # ------------------------------------------------------------------ theme
    def _theme_name(self) -> str:
        return self.cfg.gui_theme if self.cfg.gui_theme in THEME_NAMES else "midnight"

    def _apply_theme(self) -> None:
        theme = THEMES[self._theme_name()]
        self.panel_frame.set_style(theme["bg"], theme["border"], radius=22.0)
        self.panel_frame.setStyleSheet(
            f"QLabel {{ color:{theme['text']}; }}"
            f"QScrollBar:vertical {{ background:transparent; width:6px; margin:2px 0; }}"
            f"QScrollBar::handle:vertical {{ background:{theme['btn_hover']}; border-radius:3px; min-height:24px; }}"
            f"QScrollBar::handle:vertical:hover {{ background:{theme['accent']}; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}"
            f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background:transparent; }}"
        )
        self.folded_widget.set_style(theme["bg"], theme["border"], theme["text"])
        folded_font = self.folded_widget.font()
        folded_font.setBold(True)
        self.folded_widget.setFont(folded_font)
        self.status_label.setStyleSheet(f"font-size:11px; color:{theme['muted']}; background:transparent;")
        self.update_banner.setStyleSheet(
            f"QFrame#updateBanner {{ background:{theme['tab_active']}; border-radius:10px; }}"
            f"QLabel {{ color:{theme['text']}; font-size:11px; background:transparent; }}"
            f"QPushButton {{ background:{theme['btn_bg']}; color:{theme['text']}; border:none; "
            f"border-radius:7px; padding:4px 9px; font-size:11px; }}"
            f"QPushButton:hover {{ background:{theme['btn_hover']}; }}"
            f"QPushButton#updateNow {{ background:{theme['accent']}; color:#15151f; font-weight:700; }}"
            f"QPushButton:disabled {{ color:{theme['muted']}; }}")
        self.activity_updated_label.setStyleSheet(f"color:{theme['muted']}; font-size:11px; background:transparent;")

        for lbl in (self.stat_friends_label, self.stat_new_label, self.stat_rate_label):
            lbl.setStyleSheet(f"font-size:11px; font-weight:600; color:{theme['text']}; background:transparent;")
        self.ticker.set_theme(theme)

        self.fold_btn.setStyleSheet(
            f"QPushButton {{ background:{theme['btn_bg']}; color:{theme['text']}; border:none; "
            f"border-radius:8px; font-size:14px; }}"
            f"QPushButton:hover {{ background:{theme['btn_hover']}; }}"
        )
        self.settings_btn.setStyleSheet(
            f"QPushButton {{ background:{theme['btn_bg']}; color:{theme['text']}; border:none; "
            f"border-radius:8px; font-size:13px; }}"
            f"QPushButton:hover {{ background:{theme['btn_hover']}; }}"
        )
        self.settings_panel.setStyleSheet(f"#settings {{ background:{theme['card_bg']}; border-radius:12px; }}")
        self.opacity_value_label.setStyleSheet(f"font-size:10.5px; color:{theme['muted']}; background:transparent;")
        self.hearts_check.setStyleSheet(f"QCheckBox {{ font-size:11px; color:{theme['text']}; background:transparent; }}")
        self.opacity_slider.setStyleSheet(
            f"QSlider::groove:horizontal {{ height:4px; background:{theme['border']}; border-radius:2px; }}"
            f"QSlider::sub-page:horizontal {{ background:{theme['accent']}; border-radius:2px; }}"
            f"QSlider::handle:horizontal {{ background:{theme['accent']}; width:14px; height:14px; "
            f"margin:-5px 0; border-radius:7px; }}"
        )
        for name, btn in self.swatch_buttons.items():
            active = name == self._theme_name()
            border = f"2px solid {theme['accent']}" if active else f"1px solid {theme['swatch_border']}"
            btn.setStyleSheet(
                f"QPushButton {{ background:{SWATCH_GRADIENTS[name]}; border-radius:7px; border:{border}; }}"
            )
        for btn in (self.refresh_sugg_btn, self.refresh_repos_btn, self.refresh_market_btn, self.refresh_act_btn,
                    self.refresh_signals_btn):
            btn.setStyleSheet(
                f"QPushButton {{ background:{theme['section_btn']}; color:{theme['text']}; border:none; "
                f"border-radius:8px; padding:6px 10px; font-size:11.5px; }}"
            )
        self.chart.set_theme_colors(theme["text"], theme["accent"])
        self.auc_gauge.set_theme_colors(theme["text"])
        self.weight_bars.set_theme_colors(theme["text"], theme["accent"])
        for tile in self.model_tiles.values():
            tile.apply_theme(theme)
        for label in self.model_section_labels:
            label.setStyleSheet(f"color:{theme['muted']}; font-size:10.5px; font-weight:600; "
                                f"background:transparent;")
        for label in (self.weights_hint, self.model_footer_label, self.model_delta_label):
            label.setStyleSheet(f"color:{theme['muted']}; font-size:10.5px; background:transparent;")
        self.model_summary_label.setStyleSheet(f"color:{theme['text']}; font-size:11.5px; background:transparent;")
        self._style_model_grade()
        self._update_tab_styles()

    def _update_tab_styles(self) -> None:
        theme = THEMES[self._theme_name()]
        for name, btn in self.tab_buttons.items():
            active = name == self.active_tab
            bg = theme["tab_active"] if active else theme["card_bg"]
            btn.setStyleSheet(
                f"QPushButton {{ background:{bg}; color:{theme['text']}; border:none; "
                f"border-radius:8px; padding:6px 0; font-size:11px; }}"
            )

    def _on_theme_clicked(self, name: str) -> None:
        if logic.set_theme(self.cfg, name):
            self._apply_theme()
            self._render_suggestions_from_cache()
            self._load_market()

    def _render_suggestions_from_cache(self) -> None:
        # Re-render already-loaded cards so their theme-dependent styling updates too.
        self._load_suggestions()
        if not self._contrib_running:  # don't wipe the "Searching…" placeholder mid-search
            self._load_contributions()
        self._refresh_activity(force=False)
        self._refresh_signals(force=False)  # cached unless due: just re-renders

    # ------------------------------------------------------------------ fold/unfold/dock
    def _dock(self, folded: bool) -> None:
        # the screen the panel is on now (it stays there when folded/unfolded)
        screen = self.screen() or QGuiApplication.primaryScreen()
        rect = screen.availableGeometry()  # excludes the taskbar
        self.panel_frame.setVisible(not folded)
        self.folded_widget.setVisible(folded)
        # the folded tab is sized purely by config; the full panel can't go
        # below what its content needs, so position it by that real size
        need = QSize(0, 0) if folded else self.panel_frame.minimumSizeHint()
        x, y, w, h = logic._panel_geometry(self.cfg, folded, rect, need.width(), need.height())
        self.setMinimumSize(0, 0)
        self.setGeometry(x, y, w, h)
        self.setWindowOpacity(self.cfg.gui_folded_opacity if folded else self.cfg.gui_opacity)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 -- Qt's own naming convention
        if obj is self.folded_widget and self.folded_widget.isVisible():
            if event.type() == QEvent.Enter:
                self.setWindowOpacity(1.0)
            elif event.type() == QEvent.Leave:
                self.setWindowOpacity(self.cfg.gui_folded_opacity)
        return super().eventFilter(obj, event)

    def fold(self) -> None:
        self._dock(folded=True)

    def unfold(self) -> None:
        self._dock(folded=False)
        self.hearts.hide()

    def closeEvent(self, event) -> None:  # noqa: N802 -- Qt's own naming convention
        self.hearts.close()  # a separate top-level window; it would outlive the panel
        super().closeEvent(event)

    # ------------------------------------------------------------------ native window effects
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # DWM's Acrylic system backdrop (DWMWA_SYSTEMBACKDROP_TYPE) was tried
        # here and confirmed, through isolated side-by-side testing, to
        # conflict with Qt's own WA_TranslucentBackground on this class of
        # setup: layering the DWM call on top of an otherwise genuinely
        # transparent Qt window made it render fully opaque instead --
        # reproduced with focus and without. Qt's own translucency (real,
        # working, see-through) is what actually ships; no DWM call here.

    # ------------------------------------------------------------------ async helper
    def _run_async(self, fn: Callable[[], Any], on_done: Callable[[Any], None]) -> None:
        worker = _Worker(fn)

        def _finish(result: Any) -> None:
            on_done(result)
            if worker in self._workers:
                self._workers.remove(worker)

        worker.done.connect(_finish)
        self._workers.append(worker)
        worker.start()

    # ------------------------------------------------------------------ status / suggestions
    def _load_status(self) -> None:
        status = logic.get_status(self.cfg)
        if status["configured"]:
            extra = "" if status["token_present"] else " (no token set — run `mygeeky auth login`)"
            self.status_label.setText(f"Signed in as {status['github_username']}{extra}")
        else:
            self.status_label.setText("Run `mygeeky init` in a terminal to get started.")

    def _load_live_stats(self) -> None:
        stats = logic.get_friend_stats(self.cfg)
        self.stat_friends_label.setText(f"👥 {stats['total_friends']} friends")
        self.stat_new_label.setText(f"🆕 {stats['new_this_week']} new this week")
        rate = stats["follow_back_rate"]
        self.stat_rate_label.setText(f"🔁 {rate:.0%} follow back" if rate is not None else "🔁 no data yet")

    def _load_suggestions(self) -> None:
        self._render_suggestions(logic.get_suggestions(self.cfg))

    def _maybe_auto_refresh_suggestions(self) -> None:
        if not self._sugg_running and logic.suggestions_auto_refresh_due(self.cfg):
            self._on_refresh_suggestions()

    def _on_refresh_suggestions(self) -> None:
        if self._sugg_running:
            return  # a search is already in flight; don't stack another
        self._sugg_running = True
        self.refresh_sugg_btn.setEnabled(False)
        theme = THEMES[self._theme_name()]
        _clear_layout(self.followback_area)
        loading = QLabel("Searching GitHub… this can take a minute.")
        loading.setStyleSheet(f"color:{theme['muted']}; font-size:11px; background:transparent;")
        self.followback_area.addWidget(loading)
        self._run_async(lambda: logic.refresh_suggestions(self.cfg), self._on_suggestions_ready)

    def _on_suggestions_ready(self, data: Any) -> None:
        self._sugg_running = False
        self.refresh_sugg_btn.setEnabled(True)
        if isinstance(data, dict) and data.get("error") and "followback" not in data:
            theme = THEMES[self._theme_name()]
            _clear_layout(self.followback_area)
            err = QLabel(str(data["error"]))
            err.setWordWrap(True)
            err.setStyleSheet(f"color:{theme['muted']}; font-size:11px; background:transparent;")
            self.followback_area.addWidget(err)
            return
        self._render_suggestions(data)

    def _render_suggestions(self, data: dict[str, Any] | None) -> None:
        theme = THEMES[self._theme_name()]
        followback = (data or {}).get("followback") or []
        domain = (data or {}).get("domain_highlights") or []
        self._set_card_list(self.followback_area, followback, "score", theme)
        self._set_card_list(self.domain_area, domain, "domain_fit", theme)
        self._last_suggestions = followback
        self._update_live_ticker()

    def _set_card_list(self, layout, items: list[dict[str, Any]], score_key: str, theme: dict[str, Any]) -> None:
        _clear_layout(layout)
        if not items:
            empty = QLabel("Nothing here yet — try Refresh.")
            empty.setStyleSheet(f"color:{theme['muted']}; font-size:11px; background:transparent;")
            layout.addWidget(empty)
            return
        for item in items:
            layout.addWidget(SuggestionCard(item, score_key, theme, self._on_suggestion_clicked, self.avatar_loader))

    def _on_suggestion_clicked(self, item: dict[str, Any]) -> None:
        logic.open_profile(item.get("profile_url", ""))
        logic.mark_suggestion_seen(item.get("username", ""))
        # re-render on the next event-loop turn: the clicked card is still
        # inside its own mousePressEvent right now
        QTimer.singleShot(0, self._load_suggestions)

    def _on_ticker_clicked(self, url: str) -> bool:
        opened = logic.open_profile(url)
        suggestion = next((s for s in self._last_suggestions if s.get("profile_url") == url), None)
        if suggestion:  # activity cards are people you already follow -- only suggestions get dropped
            logic.mark_suggestion_seen(suggestion.get("username", ""))
            QTimer.singleShot(0, self._load_suggestions)
        return opened

    # ------------------------------------------------------------------ repos (contribute)
    def _load_contributions(self) -> None:
        self._render_contributions(logic.get_contributions(self.cfg))

    def _on_refresh_contributions(self) -> None:
        if self._contrib_running:
            return  # a repo search is already in flight; don't stack another
        self._contrib_running = True
        self.refresh_repos_btn.setEnabled(False)
        theme = THEMES[self._theme_name()]
        _clear_layout(self.repos_area)
        loading = QLabel("Searching GitHub for repos… this can take a few minutes (rate-limited search API).")
        loading.setWordWrap(True)
        loading.setStyleSheet(f"color:{theme['muted']}; font-size:11px; background:transparent;")
        self.repos_area.addWidget(loading)
        self._run_async(lambda: logic.refresh_contributions(self.cfg), self._on_contributions_ready)

    def _on_contributions_ready(self, data: Any) -> None:
        self._contrib_running = False
        self.refresh_repos_btn.setEnabled(True)
        if isinstance(data, dict) and data.get("error"):
            theme = THEMES[self._theme_name()]
            _clear_layout(self.repos_area)
            err = QLabel(str(data["error"]))
            err.setWordWrap(True)
            err.setStyleSheet(f"color:{theme['muted']}; font-size:11px; background:transparent;")
            self.repos_area.addWidget(err)
            return
        self._render_contributions(data)

    def _render_contributions(self, items: list[dict[str, Any]] | None) -> None:
        theme = THEMES[self._theme_name()]
        _clear_layout(self.repos_area)
        if not items:
            empty = QLabel("No repo suggestions yet — click Refresh, or run `mygeeky contribute`.")
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color:{theme['muted']}; font-size:11px; background:transparent;")
            self.repos_area.addWidget(empty)
            return
        for item in items:
            self.repos_area.addWidget(RepoCard(item, theme, logic.open_profile, self.avatar_loader))

    # ------------------------------------------------------------------ activity
    def _refresh_activity(self, force: bool) -> None:
        self._run_async(lambda: logic.get_activity(self.cfg, force=force), self._on_activity_ready)

    def _on_activity_ready(self, data: Any) -> None:
        theme = THEMES[self._theme_name()]
        events = (data or {}).get("events") or []
        _clear_layout(self.activity_area)
        if not events:
            empty = QLabel("No recent activity from people you follow or your profile matches yet.")
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color:{theme['muted']}; font-size:11px; background:transparent;")
            self.activity_area.addWidget(empty)
        else:
            for group in logic.group_activity(events):
                card = ActivityGroup(group, theme, logic.open_profile, self.avatar_loader,
                                     expanded=group["actor"].lower() in self._expanded_actors)
                card.toggled.connect(self._on_activity_group_toggled)
                self.activity_area.addWidget(card)
        fetched_at = (data or {}).get("fetched_at")
        if fetched_at:
            self.activity_updated_label.setText("updated " + _time_ago(fetched_at))
        self._last_activity_events = events
        if not (data or {}).get("cached"):
            self._load_suggestions()  # the refresh also re-read who you follow
        self._update_live_ticker()

    def _on_activity_group_toggled(self, actor: str, expanded: bool) -> None:
        if expanded:
            self._expanded_actors.add(actor.lower())
        else:
            self._expanded_actors.discard(actor.lower())

    # ------------------------------------------------------------------ signals
    def _refresh_signals(self, force: bool) -> None:
        if self._signals_running:
            return
        self._signals_running = True
        self._run_async(lambda: logic.get_signals(self.cfg, force=force), self._on_signals_ready)

    def _on_signals_ready(self, data: Any) -> None:
        self._signals_running = False
        data = data or {}
        self._render_signals(data)
        self._last_incoming = data.get("incoming") or []
        self._update_live_ticker()

    def _render_signals(self, data: dict[str, Any]) -> None:
        theme = THEMES[self._theme_name()]
        _clear_layout(self.signals_area)
        muted = f"color:{theme['muted']}; font-size:10.5px; background:transparent;"
        self.signals_hint.setStyleSheet(muted)
        self.signals_updated_label.setStyleSheet(muted)
        if not data.get("enabled"):
            self.signals_hint.setText(
                "Send other myGeeKy users emoji signals (👋 📚 🤝 👀) and see theirs to you. Signals are public. "
                "To join, run `mygeeky beacon init` in a terminal.")
            self.refresh_signals_btn.setEnabled(False)
            return
        self.refresh_signals_btn.setEnabled(True)
        self.signals_hint.setText("👋 wave · 📚 I learn from you · 🤝 let's collaborate · 👀 following your work. "
                                  "Signals are public, and 🤝 handshake means you've both signalled.")
        fetched = data.get("fetched_at")
        self.signals_updated_label.setText(data.get("error") or ("updated " + _time_ago(fetched) if fetched else ""))
        on_send = self._on_send_signal if data.get("can_send") else None

        def header(text: str) -> None:
            lbl = QLabel(text)
            lbl.setStyleSheet("font-size:10.5px; font-weight:700; letter-spacing:0.5px; "
                              f"margin-top:6px; color:{theme['text']}; background:transparent;")
            self.signals_area.addWidget(lbl)

        incoming = data.get("incoming") or []
        header("FOR YOU")
        if not incoming:
            empty = QLabel("No signals yet. Say hi to someone below.")
            empty.setStyleSheet(muted)
            self.signals_area.addWidget(empty)
        for item in incoming:
            self.signals_area.addWidget(SignalCard(item, theme, logic.open_profile, on_send, self.avatar_loader))
        people = data.get("people") or []
        header("FELLOW GEEKS ON MYGEEKY")
        if not people:
            empty = QLabel("No other beacons found yet.")
            empty.setStyleSheet(muted)
            self.signals_area.addWidget(empty)
        for item in people:
            self.signals_area.addWidget(SignalCard(item, theme, logic.open_profile, on_send, self.avatar_loader))

    def _on_send_signal(self, card: "SignalCard", login: str, gesture: str) -> None:
        card.set_busy(True)
        card.show_result("sending…")

        def done(result: Any) -> None:
            card.set_busy(False)
            ok = isinstance(result, dict) and result.get("ok")
            card.show_result("sent ✓" if ok else "failed")
            if not ok:
                card.setToolTip((result or {}).get("error", "") if isinstance(result, dict) else "")
        self._run_async(lambda: logic.send_signal(self.cfg, login, gesture), done)

    # ------------------------------------------------------------------ market
    def _load_market(self) -> None:
        self._render_market(logic.get_market(self.cfg))

    def _maybe_refresh_market(self) -> None:
        if logic.market_refresh_due(self.cfg):
            self._refresh_market(force=False)

    def _refresh_market(self, force: bool) -> None:
        if self._market_running:
            return  # a snapshot is already running; it takes a few minutes
        self._market_running = True
        self.refresh_market_btn.setEnabled(False)
        self.market_updated_label.setText("updating… (a few minutes)")
        self._run_async(lambda: logic.refresh_market(self.cfg, force=force), self._on_market_ready)

    def _on_market_ready(self, data: Any) -> None:
        self._market_running = False
        self.refresh_market_btn.setEnabled(True)
        self._render_market(data or {})

    def _render_market(self, data: dict[str, Any]) -> None:
        theme = THEMES[self._theme_name()]
        rows = data.get("rows") or []
        _clear_layout(self.market_area)
        if data.get("error") or not rows:
            msg = QLabel(data.get("error") or "No board yet — it builds itself in the background "
                                              "(or click Refresh). The first run takes a few minutes.")
            msg.setWordWrap(True)
            msg.setStyleSheet(f"color:{theme['muted']}; font-size:11px; background:transparent;")
            self.market_area.addWidget(msg)
        for row in rows:
            self.market_area.addWidget(MarketRow(row, theme, logic.open_profile, self.avatar_loader))
        self._render_producthunt(data, theme)
        collecting = rows and all(r.get("stars_week") is None for r in rows)
        self.market_hint.setText(
            "The popular, active repos in your field, ranked by momentum: stars gained, commits and PyPI "
            "downloads. ▲▼ = places moved since the last day ranked."
            + (" Star gains appear once there's a day of snapshots." if collecting else ""))
        updated = data.get("updated_at")
        if not self._market_running:
            self.market_updated_label.setText("updated " + _time_ago(updated) if updated else "")
        self.market_hint.setStyleSheet(f"color:{theme['muted']}; font-size:10.5px; background:transparent;")
        self.market_updated_label.setStyleSheet(f"color:{theme['muted']}; font-size:11px; background:transparent;")

    def _render_producthunt(self, data: dict[str, Any], theme: dict[str, Any]) -> None:
        posts = data.get("producthunt") or []
        header = QLabel("PRODUCT HUNT · LAUNCHES IN YOUR FIELD")
        header.setStyleSheet("font-size:10.5px; font-weight:700; letter-spacing:0.5px; "
                             f"margin-top:8px; color:{theme['text']}; background:transparent;")
        self.market_area.addWidget(header)
        if not posts:
            hint = QLabel("Add launches from Product Hunt: run `mygeeky auth producthunt` in a terminal "
                          "(a free developer token), then click Refresh."
                          if not data.get("producthunt_token") else
                          "No launches yet. They load with the next board refresh (or click Refresh).")
            hint.setWordWrap(True)
            hint.setStyleSheet(f"color:{theme['muted']}; font-size:10.5px; background:transparent;")
            self.market_area.addWidget(hint)
            return
        for post in posts:
            self.market_area.addWidget(ProductHuntRow(post, theme, logic.open_link, self.avatar_loader))

    # ------------------------------------------------------------------ live spotlight ticker
    def _update_live_ticker(self) -> None:
        items = _build_spotlight_items(self._last_activity_events, self._last_suggestions,
                                       getattr(self, "_last_incoming", []))
        was_running = self.ticker.is_running()
        self.ticker.set_items(items)
        if was_running:
            self.ticker.start(int(self.cfg.gui_live_rotate_seconds * 1000))

    # ------------------------------------------------------------------ model
    def _load_model_history(self) -> None:
        self._render_model(logic.get_model_history())

    def _render_model(self, history: list[dict[str, Any]]) -> None:
        latest = history[-1] if history else {}
        prev = history[-2] if len(history) > 1 else {}
        auc = latest.get("auc")
        grade, explanation = logic.auc_verdict(auc)
        self._model_auc = auc
        self.auc_gauge.set_auc(auc)
        self.model_grade_label.setText(grade)
        self.model_summary_label.setText(explanation)
        self._style_model_grade()

        if auc is not None and prev.get("auc") is not None:
            diff = auc - prev["auc"]
            arrow = "▲" if diff > 0.001 else "▼" if diff < -0.001 else "●"
            self.model_delta_label.setText(f"{arrow} {diff:+.3f} since the previous retrain")
        else:
            self.model_delta_label.setText("")

        n_train, n_pos = latest.get("n_train") or 0, latest.get("n_pos") or 0
        self.model_tiles["examples"].set_value(n_train)
        self.model_tiles["positives"].set_value(n_pos)
        self.model_tiles["rate"].set_value(100 * n_pos / n_train if n_train else 0, lambda v: f"{v:.0f}%")
        self.model_tiles["retrains"].set_value(len(history))

        self.weight_bars.set_weights(logic.get_model_weights())
        self.chart.set_history(history)
        if latest.get("timestamp"):
            self.model_footer_label.setText(
                f"Last retrained {_time_ago(latest['timestamp'])}. Follow people you like, then run "
                f"mygeeky learn -- every follow-back you get teaches it more. Hover the chart for details.")
        else:
            self.model_footer_label.setText("No retrains yet -- run mygeeky bootstrap, then mygeeky learn.")

    def _style_model_grade(self) -> None:
        color = _auc_color(getattr(self, "_model_auc", None)).name()
        self.model_grade_label.setStyleSheet(
            f"color:{color}; font-size:20px; font-weight:700; background:transparent;")

    def _play_model_animations(self) -> None:
        for widget in (self.auc_gauge, self.weight_bars, self.chart, *self.model_tiles.values()):
            widget.play()

    # ------------------------------------------------------------------ tabs
    def _switch_tab(self, name: str) -> None:
        self.active_tab = name
        self.content_stack.setCurrentIndex(self._tab_order.index(name))
        self._update_tab_styles()
        if name == "model":  # re-read (it's a local file) and replay the entrance
            self._load_model_history()
            self._play_model_animations()
