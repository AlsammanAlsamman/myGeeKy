"""The Qt widget tree for the live glass panel. Kept separate from app.py
so app.py (and its business-logic functions) can be imported/tested without
requiring PySide6 to be importable."""

from __future__ import annotations

import hashlib
import html
import math
import os
import sys
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import (
    QByteArray,
    QRect,
    QStringListModel,
    QUrl,
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
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import (
    QDesktopServices,
    QBrush,
    QColor,
    QGuiApplication,
    QIcon,
    QCursor,
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
    QCompleter,
    QProgressBar,
    QDialog,
    QMessageBox,
    QLineEdit,
    QPlainTextEdit,
    QRadioButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
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
SYNC_EVERY_MS = 15 * 60 * 1000   # how often the panel syncs your data between computers
DOCK_GUARD_MS = 3000   # how often the panel checks it is still docked where it belongs
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


def _alive(w: QWidget) -> bool:
    """False once Qt has deleted the widget behind this Python object."""
    try:
        w.objectName()
        return True
    except RuntimeError:
        return False


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


def _explore_chip(theme: dict[str, Any]) -> QLabel:
    """Marks an item from outside your usual interests (see interests.mix)."""
    chip = QLabel("🔭 new territory")
    chip.setToolTip("Outside your usual interests, on purpose: a little room to discover something new. "
                    "Clicking it teaches myGeeKy that this interests you too.")
    chip.setStyleSheet(f"color:{theme['text']}; background:rgba(122,92,255,70); border-radius:7px; "
                       f"padding:1px 6px; font-size:9.5px;")
    chip.setFixedHeight(16)
    return chip


NEWS_BADGES = {"arxiv": ("arXiv", "#b31b1b"), "biorxiv": ("bioRxiv", "#bd2736"), "hackernews": ("HN", "#ff6600")}


HEADLINE_COLORS = {"ai": "#ff6fd8", "science": "#34d399", "tech": "#7fd8ff"}


class HeadlineRow(QFrame):
    """One headline: a small source tag and the title. Click to read it."""

    def __init__(self, item: dict[str, Any], theme: dict[str, Any], on_open: Callable[[str], bool]) -> None:
        super().__init__()
        self.setObjectName("headlineRow")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(7)
        color = HEADLINE_COLORS.get(item.get("category", ""), theme["muted"])
        tag = QLabel(("\U0001f30d " if item.get("explore") else "") + item.get("source", ""))
        tag.setTextFormat(Qt.PlainText)
        tag.setFixedWidth(92)
        tag.setStyleSheet(f"color:{color}; font-size:9.5px; font-weight:700; background:transparent;")
        tag.setToolTip("\U0001f30d the big picture: outside your usual interests" if item.get("explore")
                       else "for you: " + ", ".join(item.get("match") or []))
        lay.addWidget(tag, 0, Qt.AlignTop)
        from ..badges import BADGES, item_kind
        kind = item_kind(item)
        lay.addWidget(letter_badge(kind, f"{BADGES[kind][0].capitalize()}"), 0, Qt.AlignTop)
        title = QLabel(item.get("title", ""))
        title.setTextFormat(Qt.PlainText)
        title.setWordWrap(True)
        title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        title.setStyleSheet(f"color:{theme['text']}; font-size:11px; background:transparent;")
        lay.addWidget(title, 1)
        when = QLabel(_time_ago(item.get("published", "")))
        when.setStyleSheet(f"color:{theme['muted']}; font-size:9.5px; background:transparent;")
        lay.addWidget(when, 0, Qt.AlignTop)
        self.setStyleSheet(f"QFrame#headlineRow {{ background:transparent; border-radius:8px; }}"
                           f"QFrame#headlineRow:hover {{ background:{theme['card_bg']}; }}")
        self.setCursor(Qt.PointingHandCursor)
        link = item.get("link", "")
        self.mousePressEvent = lambda ev: on_open(link)  # noqa: ARG005


class NewsCard(QFrame):
    """One news item: source badge, title, why it's here (matching terms, or
    🔭 new territory) and when. Text from the source is shown as plain text.
    Clicking opens it (and counts as an interest signal)."""

    def __init__(self, item: dict[str, Any], theme: dict[str, Any], on_open: Callable[[str], bool]) -> None:
        super().__init__()
        self.setObjectName("newsCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(3)
        top = QHBoxLayout()
        top.setSpacing(6)
        name, color = NEWS_BADGES.get(item.get("source", ""), (item.get("source", ""), theme["accent"]))
        badge = QLabel(name)
        badge.setStyleSheet(f"color:white; background:{color}; border-radius:6px; padding:0 6px; "
                            f"font-size:9.5px; font-weight:700;")
        badge.setFixedHeight(15)
        top.addWidget(badge)
        from ..badges import BADGES, item_kind
        kind = item_kind(item)
        top.addWidget(letter_badge(kind, BADGES[kind][0].capitalize()))
        if item.get("explore"):
            top.addWidget(_explore_chip(theme))
        top.addStretch(1)
        when = QLabel(_time_ago(item.get("published", "")))
        when.setStyleSheet(f"color:{theme['muted']}; font-size:10px; background:transparent;")
        top.addWidget(when)
        outer.addLayout(top)
        title = QLabel(item.get("title", ""))
        title.setTextFormat(Qt.PlainText)
        title.setWordWrap(True)
        title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        title.setStyleSheet(f"color:{theme['text']}; font-size:11.5px; font-weight:600; background:transparent;")
        outer.addWidget(title)
        why = ", ".join(item.get("match") or [])
        if why and not item.get("explore"):
            sub = QLabel(f"matches {why}")
            sub.setTextFormat(Qt.PlainText)
            sub.setWordWrap(True)
            sub.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            sub.setStyleSheet(f"color:{theme['muted']}; font-size:10px; background:transparent;")
            outer.addWidget(sub)
        self.setToolTip(item.get("summary", ""))
        self.setStyleSheet(f"QFrame#newsCard {{ background:{theme['card_bg']}; border-radius:10px; }}"
                           f"QFrame#newsCard:hover {{ background:{theme['btn_bg']}; }}")
        self.setCursor(Qt.PointingHandCursor)
        url = item.get("url", "")
        self.mousePressEvent = lambda ev: on_open(url)  # noqa: ARG005


PUBLISHED_GREEN = "#22c55e"


def letter_badge(letter: str, tooltip: str, url: str = "",
                 on_open: Callable[[str], bool] | None = None) -> QPushButton:
    """P (paper, green) · N (news, yellow) · D (discussion, blue) · A (announcement,
    violet): one small square, one meaning, everywhere. Clickable when it has a link."""
    from ..badges import BADGES
    color = BADGES[letter][1]
    badge = QPushButton(letter)
    badge.setFixedSize(18, 18)
    badge.setToolTip(tooltip)
    text = "#1a1a1a" if letter == "N" else "white"          # dark on yellow reads better
    badge.setStyleSheet(f"QPushButton {{ background:{color}; color:{text}; border:none; border-radius:4px; "
                        f"font-size:10px; font-weight:800; padding:0; }}")
    if url and on_open is not None:
        badge.setCursor(Qt.PointingHandCursor)
        badge.clicked.connect(lambda: on_open(url))
    return badge


def published_badge(paper: dict[str, Any], on_open: Callable[[str], bool]) -> QPushButton:
    """The green [P]: this repo has a published paper. Click to open it."""
    cited = paper.get("cited")
    title = paper.get("title") or paper.get("doi") or "a paper"
    year = (paper.get("date") or "")[:4]
    return letter_badge("P", f"Published: {title}" + (f" ({year})" if year else "")
                        + (f" · cited {cited} times" if cited else "") + "\nClick to open the paper.",
                        paper.get("url", ""), on_open)


def news_badge(story: dict[str, Any], on_open: Callable[[str], bool]) -> QPushButton:
    """The yellow [N] (in the news) or blue [D] (discussed on Hacker News) on a repo."""
    what = "In the news" if story["kind"] == "N" else "Discussed on Hacker News"
    return letter_badge(story["kind"], f"{what} this week: {story.get('title', '')}\nClick to read it.",
                        story.get("url", ""), on_open)


BADGE_LEGEND = ("<span style='color:#22c55e'>■</span> P paper &nbsp; <span style='color:#eab308'>■</span> N news "
                "&nbsp; <span style='color:#38bdf8'>■</span> D discussion &nbsp; "
                "<span style='color:#a78bfa'>■</span> A announcement")


class ResearchCard(QFrame):
    """A paper: why it's trending, title, venue and citations, lead authors,
    and its GitHub repo. Clicking expands it: open the paper or the repo, and
    see the people working on the repo (loaded on first expand)."""

    def __init__(self, paper: dict[str, Any], theme: dict[str, Any], on_open: Callable[[str], bool],
                 on_open_repo: Callable[[str], bool], on_people: Callable[["ResearchCard", str], None] | None,
                 loader: "AvatarLoader | None" = None, kind: str = "rising") -> None:
        super().__init__()
        self.setObjectName("researchCard")
        self.paper, self.theme, self.loader = paper, theme, loader
        self._on_people, self._people_loaded = on_people, False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(3)

        self.header = QWidget()
        self.header.setCursor(Qt.PointingHandCursor)
        head = QVBoxLayout(self.header)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(3)
        top = QHBoxLayout()
        top.setSpacing(6)
        v = paper.get("velocity", 0) or 0
        per_month = round(v) if v >= 10 else round(v, 1)
        trend = QLabel(f"🔥 {per_month}/month" if kind == "rising"
                       else f"🛠️ {paper.get('cited', 0)} citations")
        trend.setToolTip("Citations per month since it was published" if kind == "rising" else
                         "A recent tool in your field, with a paper and its code on GitHub")
        trend.setStyleSheet(f"color:{theme['text']}; background:{theme['section_btn']}; border-radius:7px; "
                            f"padding:1px 6px; font-size:9.5px;")
        trend.setFixedHeight(16)
        top.addWidget(trend)
        if paper.get("repos"):
            top.addWidget(published_badge(paper, on_open))
        if paper.get("explore"):
            top.addWidget(_explore_chip(theme))
        top.addStretch(1)
        year = QLabel((paper.get("date") or "")[:4])
        year.setStyleSheet(f"color:{theme['muted']}; font-size:10px; background:transparent;")
        top.addWidget(year)
        head.addLayout(top)
        title = QLabel(paper.get("title", ""))
        title.setTextFormat(Qt.PlainText)
        title.setWordWrap(True)
        title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        title.setStyleSheet(f"color:{theme['text']}; font-size:11.5px; font-weight:600; background:transparent;")
        head.addWidget(title)
        authors = paper.get("authors") or []
        who = authors[0]["name"] if authors else ""
        if len(authors) > 1:
            who += f" … {authors[-1]['name']}"
        meta_bits = [b for b in (paper.get("venue"), f"cited {paper.get('cited', 0)}", who) if b]
        if paper.get("repos"):
            meta_bits.append("code: " + paper["repos"][0])
        meta = QLabel(" · ".join(meta_bits))
        meta.setTextFormat(Qt.PlainText)
        meta.setWordWrap(True)
        meta.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        meta.setStyleSheet(f"color:{theme['muted']}; font-size:10px; background:transparent;")
        head.addWidget(meta)
        outer.addWidget(self.header)

        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 4, 0, 0)
        body.setSpacing(4)
        buttons = QHBoxLayout()
        btn_style = (f"QPushButton {{ background:{theme['btn_bg']}; color:{theme['text']}; border:none; "
                     f"border-radius:7px; padding:4px 9px; font-size:10.5px; }}"
                     f"QPushButton:hover {{ background:{theme['btn_hover']}; }}")
        paper_btn = QPushButton("Paper ↗")
        paper_btn.setStyleSheet(btn_style)
        paper_btn.setCursor(Qt.PointingHandCursor)
        url = paper.get("url", "")
        paper_btn.clicked.connect(lambda: on_open(url))
        buttons.addWidget(paper_btn)
        for repo in (paper.get("repos") or [])[:2]:
            b = QPushButton(f"{repo} ↗")
            b.setStyleSheet(btn_style)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda checked=False, r=repo: on_open_repo(f"https://github.com/{r}"))
            buttons.addWidget(b)
        buttons.addStretch(1)
        body.addLayout(buttons)
        self.people_box = QVBoxLayout()
        self.people_box.setSpacing(3)
        body.addLayout(self.people_box)
        outer.addWidget(self.body)
        self.body.setVisible(False)

        self.setStyleSheet(f"QFrame#researchCard {{ background:{theme['card_bg']}; border-radius:10px; }}")
        self.setToolTip(paper.get("abstract", ""))
        self.header.mousePressEvent = lambda ev: self.toggle()  # noqa: ARG005

    def toggle(self) -> None:
        # isHidden(), not isVisible(): the latter is False whenever the window itself isn't shown
        expanded = self.body.isHidden()
        self.body.setVisible(expanded)
        repos = self.paper.get("repos") or []
        if expanded and repos and self._on_people and not self._people_loaded:
            self._people_loaded = True
            note = QLabel("Finding the people working on it…")
            note.setStyleSheet(f"color:{self.theme['muted']}; font-size:10px; background:transparent;")
            self.people_box.addWidget(note)
            self._on_people(self, repos[0])

    def set_people(self, people: list[dict[str, Any]], on_open: Callable[[str], bool]) -> None:
        _clear_layout(self.people_box)
        if not people:
            note = QLabel("No one found on GitHub for this repo.")
            note.setStyleSheet(f"color:{self.theme['muted']}; font-size:10px; background:transparent;")
            self.people_box.addWidget(note)
            return
        head = QLabel("PEOPLE WORKING ON IT")
        head.setStyleSheet(f"color:{self.theme['muted']}; font-size:9.5px; font-weight:700; background:transparent;")
        self.people_box.addWidget(head)
        for person in people:
            row = QFrame()
            row.setObjectName("personRow")
            lay = QHBoxLayout(row)
            lay.setContentsMargins(2, 2, 2, 2)
            lay.setSpacing(6)
            lay.addWidget(_avatar_widget(person["login"], person.get("avatar", ""), 20, self.loader))
            name = QLabel(person["login"])
            name.setTextFormat(Qt.PlainText)
            name.setStyleSheet(f"color:{self.theme['text']}; font-size:10.5px; font-weight:600; background:transparent;")
            lay.addWidget(name)
            role = QLabel(person.get("role", ""))
            role.setTextFormat(Qt.PlainText)
            role.setStyleSheet(f"color:{self.theme['muted']}; font-size:10px; background:transparent;")
            lay.addWidget(role)
            lay.addStretch(1)
            row.setCursor(Qt.PointingHandCursor)
            row.setToolTip(f"Open {person['login']}'s GitHub profile")
            row.setStyleSheet(f"QFrame#personRow {{ border-radius:6px; }}"
                              f"QFrame#personRow:hover {{ background:{self.theme['btn_bg']}; }}")
            login = person["login"]
            row.mousePressEvent = lambda ev, u=login: on_open(f"https://github.com/{u}")  # noqa: ARG005
            self.people_box.addWidget(row)


class ResearcherRow(QFrame):
    """Someone who keeps leading the trending papers; opens their ORCID or OpenAlex page."""

    def __init__(self, person: dict[str, Any], theme: dict[str, Any], on_open: Callable[[str], bool]) -> None:
        super().__init__()
        self.setObjectName("researcherRow")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(8)
        lay.addWidget(_avatar_label(person.get("name", "?"), 26))
        box = QVBoxLayout()
        box.setSpacing(1)
        name = QLabel(person.get("name", ""))
        name.setTextFormat(Qt.PlainText)
        name.setStyleSheet(f"color:{theme['text']}; font-size:11.5px; font-weight:600; background:transparent;")
        box.addWidget(name)
        n = person.get("papers", 0)
        stats = QLabel(f"{n} trending paper{'s' if n != 1 else ''} · {person.get('citations', 0)} citations")
        stats.setStyleSheet(f"color:{theme['muted']}; font-size:10px; background:transparent;")
        box.addWidget(stats)
        lay.addLayout(box, 1)
        self.setStyleSheet(f"QFrame#researcherRow {{ background:{theme['card_bg']}; border-radius:10px; }}"
                           f"QFrame#researcherRow:hover {{ background:{theme['btn_bg']}; }}")
        url = person.get("url", "")
        if url:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip("Open their ORCID / OpenAlex profile")
            self.mousePressEvent = lambda ev: on_open(url)  # noqa: ARG005


MAP_FIELD = "#7fd8ff"      # your research field
MAP_LEARNED = "#ff6fd8"    # what you're into lately
MAP_EXPLORE = "#9b87ff"    # today's new territory


class InterestMap(QWidget):
    """Your interests as a slowly turning constellation: you in the middle,
    your research field on the inner ring, what you've been into lately on
    the middle ring (bigger = stronger, gently pulsing), and today's new
    territory drifting on a dashed outer ring. Hover a point for what it is."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(300)
        self.setMouseTracking(True)
        self._center = "you"
        self._nodes: list[dict[str, Any]] = []
        self._phase = 0.0
        self._intro = 1.0
        self._text = QColor("#f0f0f5")
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._intro_anim = _grow_animation(self, self._set_intro, 1400)

    def set_theme_colors(self, text_color: str) -> None:
        self._text = QColor(text_color)
        self.update()

    def set_data(self, center: str, field: list[str], learned: list[tuple[str, float]], explore: list[str]) -> None:
        self._center = center or "you"
        top = max((w for _, w in learned), default=1.0) or 1.0
        def short(topic: str) -> str:   # "Genetic Mapping and Diversity in ..." -> "Genetic Mapping"
            words = [w for w in topic.split() if w.lower() not in ("and", "in", "of", "the", "for")]
            return " ".join(words[:2])
        nodes = [{"ring": 0, "label": short(t), "size": 8.0, "color": MAP_FIELD,
                  "tip": f"{t}\nYour research field (OpenAlex topics, Scholar interests, your topics)"}
                 for t in field[:6]]
        nodes += [{"ring": 1, "label": t, "size": 5.0 + 9.0 * (w / top), "color": MAP_LEARNED,
                   "tip": f"{t}\nWhat you're into lately: strength {w:g}, learned from your clicks, follows, "
                          "stars and forks"} for t, w in learned[:10]]
        nodes += [{"ring": 2, "label": t, "size": 6.0, "color": MAP_EXPLORE,
                   "tip": f"{t}\nNew territory today: outside your usual interests, on purpose"}
                  for t in explore[:4]]
        for ring in (0, 1, 2):
            members = [n for n in nodes if n["ring"] == ring]
            step = 2 * math.pi / max(len(members), 1)
            for i, n in enumerate(members):
                # each ring starts half a step further round, so labels fall between, not on top
                n["angle"] = step * i + ring * step / 2 + ring * 0.35
        self._nodes = nodes
        self.update()

    def play(self) -> None:
        self._intro_anim.stop()
        self._intro_anim.start()

    def _set_intro(self, v: float) -> None:
        self._intro = v
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        self._timer.stop()

    def _tick(self) -> None:
        self._phase += 0.033
        self.update()

    def _geometry(self) -> tuple[float, float, list[float]]:
        w, h = self.width(), self.height()
        r = min(w, h) / 2 - 18
        return w / 2, h / 2, [r * 0.38, r * 0.72, r * 0.98]

    def _pos(self, n: dict[str, Any]) -> QPointF:
        cx, cy, radii = self._geometry()
        speed = (0.05, -0.035, 0.022)[n["ring"]]
        a = n["angle"] + self._phase * speed
        rr = radii[n["ring"]] * self._intro
        return QPointF(cx + math.cos(a) * rr, cy + math.sin(a) * rr * 0.86)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtWidgets import QToolTip
        pos = event.position()
        best, best_d = None, 18.0
        for n in self._nodes:
            p = self._pos(n)
            d = math.hypot(p.x() - pos.x(), p.y() - pos.y())
            if d < best_d:
                best, best_d = n, d
        if best:
            QToolTip.showText(event.globalPosition().toPoint(), best["tip"], self)
        else:
            QToolTip.hideText()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        cx, cy, radii = self._geometry()
        # rings
        for i, r in enumerate(radii):
            pen = QPen(QColor(255, 255, 255, 26 if i < 2 else 34), 1)
            if i == 2:
                pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(cx, cy), r * self._intro, r * 0.86 * self._intro)
        # threads from you to each point
        for n in self._nodes:
            p = self._pos(n)
            c = QColor(n["color"])
            c.setAlpha(40 if n["ring"] < 2 else 28)
            pen = QPen(c, 1)
            if n["ring"] == 2:
                pen.setStyle(Qt.DotLine)
            painter.setPen(pen)
            painter.drawLine(QPointF(cx, cy), p)
        # the points: a soft glow, a core, a label
        font = painter.font()
        font.setPointSizeF(7.6)
        painter.setFont(font)
        dots = []
        for n in self._nodes:
            p = self._pos(n)
            size = n["size"] * (1 + 0.12 * math.sin(self._phase * 2.2 + n["angle"] * 3)) if n["ring"] == 1 else n["size"]
            glow = QRadialGradient(p, size * 2.6)
            c = QColor(n["color"])
            c.setAlpha(110)
            glow.setColorAt(0, c)
            c.setAlpha(0)
            glow.setColorAt(1, c)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(glow))
            painter.drawEllipse(p, size * 2.6, size * 2.6)
            core = QColor(n["color"])
            if n["ring"] == 2:
                painter.setBrush(Qt.NoBrush)
                pen = QPen(core, 1.4)
                pen.setStyle(Qt.DashLine)
                painter.setPen(pen)
            else:
                painter.setBrush(core)
            painter.drawEllipse(p, size, size)
            dots.append((n, p, size))
        # labels last, so none collides with another label or a point: lately-into first, then
        # new territory, then your field; each tries outward, inward, above, below -- and a label
        # with no free spot is left to the hover tooltip rather than drawn on top of another
        fm = painter.fontMetrics()
        taken = [QRectF(p.x() - sz, p.y() - sz, 2 * sz, 2 * sz) for _, p, sz in dots]
        taken.append(QRectF(cx - 24, cy - 24, 48, 48))
        for n, p, size in sorted(dots, key=lambda d: (1, 2, 0).index(d[0]["ring"])):
            label = n["label"] if len(n["label"]) <= 20 else n["label"][:19] + "…"
            tw, th = fm.horizontalAdvance(label), fm.height()
            out_x = p.x() + size + 4 if p.x() >= cx else p.x() - size - 4 - tw
            in_x = p.x() - size - 4 - tw if p.x() >= cx else p.x() + size + 4
            spots = [(out_x, p.y() - th / 2), (in_x, p.y() - th / 2),
                     (p.x() - tw / 2, p.y() - size - th - 1), (p.x() - tw / 2, p.y() + size + 1)]
            own = QRectF(p.x() - size, p.y() - size, 2 * size, 2 * size)
            for x, y in spots:
                rect = QRectF(x, y, tw, th)
                if rect.left() < 1 or rect.right() > self.width() - 1 or rect.top() < 0                         or rect.bottom() > self.height():
                    continue
                if any(rect.intersects(r.adjusted(-2, -1, 2, 1)) for r in taken if r != own):
                    continue
                taken.append(rect)
                painter.setPen(self._text if n["ring"] < 2 else QColor(n["color"]))
                painter.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, label)
                break
        # you
        halo = QRadialGradient(QPointF(cx, cy), 34)
        halo.setColorAt(0, QColor(255, 111, 216, 120))
        halo.setColorAt(1, QColor(255, 111, 216, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(halo))
        painter.drawEllipse(QPointF(cx, cy), 34, 34)
        grad = QLinearGradient(cx - 16, cy - 16, cx + 16, cy + 16)
        grad.setColorAt(0, QColor("#ff6fd8"))
        grad.setColorAt(1, QColor("#7a5cff"))
        painter.setBrush(QBrush(grad))
        painter.drawEllipse(QPointF(cx, cy), 16, 16)
        font.setPointSizeF(8.5)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("white"))
        initials = "".join(w[0] for w in self._center.replace("-", " ").split()[:2]).upper() or "Y"
        painter.drawText(QRectF(cx - 16, cy - 16, 32, 32), Qt.AlignCenter, initials[:2])
        painter.end()


class ExploreDonut(QWidget):
    """How much of every list is kept for new territory."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(84, 84)
        self._share = 0.0
        self._shown = 0.0
        self._text = QColor("#f0f0f5")
        self._anim = _grow_animation(self, self._set, 1100)

    def set_theme_colors(self, text_color: str) -> None:
        self._text = QColor(text_color)
        self.update()

    def set_share(self, share: float) -> None:
        self._share = max(0.0, min(share, 1.0))
        self._shown = self._share
        self.update()

    def play(self) -> None:
        self._anim.stop()
        self._anim.start()

    def _set(self, v: float) -> None:
        self._shown = self._share * v
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(8, 8, self.width() - 16, self.height() - 16)
        painter.setPen(QPen(QColor(255, 255, 255, 30), 9, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(rect, 0, 360 * 16)
        painter.setPen(QPen(QColor(MAP_EXPLORE), 9, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(rect, 90 * 16, -int(360 * 16 * self._shown))
        painter.setPen(self._text)
        font = painter.font()
        font.setPointSizeF(11)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, f"{round(self._shown * 100)}%")
        painter.end()


# The dock's planets: each tab's colour and line icon (24x24 SVG path data).
PLANETS = {
    "live": ("#ff6fd8", "M13 2 3 14h9l-1 8 10-12h-9l1-8z"),
    "suggestions": ("#7fd8ff", "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM22 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"),
    "repos": ("#22c55e", "M6 3v12M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 9a9 9 0 0 1-9 9"),
    "market": ("#ffc457", "M22 7 13.5 15.5 8.5 10.5 2 17M16 7h6v6"),
    "news": ("#eab308", "M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-4 0v-9h4M18 14h-8M15 18h-5M10 6h8v4h-8z"),
    "activity": ("#34d399", "M22 12h-4l-3 9L9 3l-3 9H2"),
    "signals": ("#a78bfa", "M4.9 19.1a10 10 0 0 1 0-14.2M7.8 16.2a6 6 0 0 1 0-8.4M16.2 7.8a6 6 0 0 1 0 8.4M19.1 4.9a10 10 0 0 1 0 14.2M12 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z"),
    "model": ("#ffd24a", "M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z"),
    "badges": ("#f0a35e", "M12 15a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM8.2 13.9 7 23l5-3 5 3-1.2-9.1"),
    "admin": ("#94a3b8", "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"),
}


class PlanetButton(QPushButton):
    """One planet in the dock: a coloured ring with a line icon. The selected one
    swells into a filled planet with a soft halo, with a little spring to it."""

    def __init__(self, color: str, path: str) -> None:
        super().__init__("")
        self._color = QColor(color)
        self._path = path
        self._grow = 0.0
        self._hover = False
        self._dot = False
        self._selected = False
        self._bg = QColor("#1c1c2c")
        self._icons: dict[str, QSvgRenderer] = {}
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(360)
        self._anim.setEasingCurve(QEasingCurve.OutBack)
        self._anim.valueChanged.connect(self._on_grow)
        self.setFixedHeight(48)
        self.setMinimumWidth(1)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)

    def _on_grow(self, v) -> None:
        self._grow = float(v)
        self.update()

    def set_selected(self, on: bool, animate: bool = True) -> None:
        if on == self._selected and (self._grow in (0.0, 1.0) or self._anim.state() == QVariantAnimation.Running):
            return
        self._selected = on
        target = 1.0 if on else 0.0
        if animate and self.isVisible():
            self._anim.stop()
            self._anim.setEasingCurve(QEasingCurve.OutBack if on else QEasingCurve.OutCubic)
            self._anim.setStartValue(self._grow)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self._grow = target
            self.update()

    def set_dot(self, on: bool) -> None:
        self._dot = on
        self.update()

    def set_planet_bg(self, color: QColor) -> None:
        self._bg = color
        self.update()

    def _icon(self, color: QColor) -> QSvgRenderer:
        key = color.name()
        if key not in self._icons:
            svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{key}" '
                   f'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="{self._path}"/></svg>')
            self._icons[key] = QSvgRenderer(QByteArray(svg.encode()))
        return self._icons[key]

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        g = self._grow
        c = QPointF(self.width() / 2, self.height() / 2)
        r = 12 + 6 * g + (1 if self._hover and g < 0.5 else 0)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        if g > 0.01:                                       # the halo of the selected planet
            halo = QColor(self._color)
            halo.setAlpha(int(70 * min(g, 1.0)))
            painter.setPen(Qt.NoPen)
            painter.setBrush(halo)
            painter.drawEllipse(c, r + 3 * g, r + 3 * g)
        fill = QColor(
            int(self._bg.red() + (self._color.red() - self._bg.red()) * min(max(g, 0), 1)),
            int(self._bg.green() + (self._color.green() - self._bg.green()) * min(max(g, 0), 1)),
            int(self._bg.blue() + (self._color.blue() - self._bg.blue()) * min(max(g, 0), 1)))
        painter.setPen(QPen(self._color, 2))
        painter.setBrush(fill)
        painter.drawEllipse(c, r, r)
        side = r * 1.05
        icon_color = QColor("#0d0d16") if g > 0.5 else self._color
        self._icon(icon_color).render(painter, QRectF(c.x() - side / 2, c.y() - side / 2, side, side))
        if self._dot and g < 0.5:                         # something new here (e.g. a new badge)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#f0f0f5"))
            painter.drawEllipse(QPointF(c.x() + r * 0.8, c.y() - r * 0.8), 3.5, 3.5)
        painter.end()


class HeightGrip(QWidget):
    """A small handle at the bottom of the panel: drag it to make the panel taller
    or shorter (within limits). Double-click goes back to the default height."""

    def __init__(self, on_drag: Callable[[float, float, bool], None], current: Callable[[], float]) -> None:
        super().__init__()
        self._on_drag, self._current = on_drag, current
        self._start_y: float | None = None
        self._start_fraction = 0.6
        self.setFixedSize(64, 12)
        self.setCursor(Qt.SizeVerCursor)
        self.setToolTip("Drag to make the panel taller or shorter (double-click: back to normal)")

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 110 if self.underMouse() or self._start_y is not None else 55))
        painter.drawRoundedRect(QRectF(12, 4, self.width() - 24, 4), 2, 2)
        painter.end()

    def enterEvent(self, event) -> None:  # noqa: N802
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._start_y = event.globalPosition().y()
        self._start_fraction = self._current()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._start_y is not None:
            self._on_drag(event.globalPosition().y() - self._start_y, self._start_fraction, False)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._start_y is not None:
            self._on_drag(event.globalPosition().y() - self._start_y, self._start_fraction, True)
        self._start_y = None
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self._on_drag(0, 0.6, True)


class QrWidget(QWidget):
    """Paints a QR code (a matrix of dark modules) crisply at any size."""

    def __init__(self, matrix: list[list[bool]], size: int = 260) -> None:
        super().__init__()
        self._m = matrix
        self.setFixedSize(size, size)

    def set_matrix(self, matrix: list[list[bool]]) -> None:
        self._m = matrix
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._m:
            return                                     # nothing yet: leave the space empty
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("white"))
        n = len(self._m) or 1
        cell = self.width() / n
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#12121c"))
        for y, row in enumerate(self._m):
            for x, dark in enumerate(row):
                if dark:
                    painter.drawRect(QRectF(x * cell, y * cell, cell + 0.5, cell + 0.5))
        painter.end()


class PairDialog(QDialog):
    """⚙ → Connect your phone: a QR code the myGeeKy phone app scans to set
    itself up. It closes by itself after a couple of minutes."""

    def __init__(self, parent: "MyGeekyPanel", theme: dict[str, Any]) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)   # in front of the always-on-top panel
        self.setWindowTitle("Connect your phone")
        self.setMinimumWidth(340)
        self._panel = parent
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setSizeConstraint(QLayout.SetFixedSize)   # the window always fits its contents, as they change
        self.intro = QLabel("In the myGeeKy phone app, tap <b>Scan from your computer</b> and point it at this code.")
        self.intro.setWordWrap(True)
        self.intro.setFixedWidth(320)
        lay.addWidget(self.intro)
        self.wait = QLabel("Checking your GitHub token\u2026")
        lay.addWidget(self.wait, 0, Qt.AlignCenter)
        self.qr = QrWidget([])                         # its space is reserved now; the code is drawn when ready
        lay.addWidget(self.qr, 0, Qt.AlignCenter)
        self.why = QLabel("")
        self.why.setWordWrap(True)
        self.why.setFixedWidth(320)
        lay.addWidget(self.why)
        self.countdown = QLabel("")
        lay.addWidget(self.countdown)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, Qt.AlignRight)
        self.setStyleSheet(f"QDialog {{ background:#17171f; }} QLabel {{ color:{theme['text']}; font-size:11.5px; }}"
                           f"QPushButton {{ background:{theme['btn_bg']}; color:{theme['text']}; border:none; "
                           f"border-radius:7px; padding:6px 14px; }}")
        self._left = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        parent._run_async(lambda: logic.phone_pairing(parent.cfg), self._ready)

    def _ready(self, result: Any) -> None:
        result = result if isinstance(result, dict) else {}
        self.wait.setVisible(False)
        if not result.get("ok"):
            self.why.setText(result.get("error", "Couldn't make the code."))
            return
        self.qr.set_matrix(result["matrix"])
        self.why.setText(("\U0001f512 " if result["with_token"] else "") + result["why"]
                         + " Your Signals token never leaves this computer.")
        self._left = result["seconds"]
        self._tick()
        self._timer.start(1000)

    def _tick(self) -> None:
        if self._left <= 0:
            self._timer.stop()
            self.accept()                       # gone: nobody can photograph it later
            return
        self.countdown.setText(f"This code disappears in {self._left}s.")
        self._left -= 1


# a person's links elsewhere: (short mark, colour, name)
LINK_MARKS = {
    "linkedin": ("in", "#0a66c2", "LinkedIn"), "orcid": ("iD", "#a6ce39", "ORCID"),
    "scholar": ("G", "#4285f4", "Google Scholar"), "researchgate": ("RG", "#00ccbb", "ResearchGate"),
    "facebook": ("f", "#1877f2", "Facebook"), "x": ("X", "#3a3a44", "X"), "web": ("\U0001f310", "#4b5563", "Website"),
}


class ActivityChart(QWidget):
    """Thirty small bars: someone's public GitHub activity per day."""

    def __init__(self, counts: list[int], color: str) -> None:
        super().__init__()
        self.counts, self.color = counts, QColor(color)
        self.setFixedHeight(46)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        n = max(len(self.counts), 1)
        top = max(self.counts or [1]) or 1
        w = self.width() / n
        for i, c in enumerate(self.counts):
            h = 3 if c == 0 else 6 + (self.height() - 8) * c / top
            col = QColor(self.color)
            col.setAlpha(60 if c == 0 else 230)
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(i * w + 1, self.height() - h, max(w - 2, 1), h), 1.5, 1.5)
        p.end()


class ShimmerBar(QWidget):
    """A slim loading bar: a pink-to-violet glow sweeping across a faint track."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(5)
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self) -> None:
        self._t = (self._t + 0.012) % 1.0
        self.update()

    def stop(self) -> None:
        self._timer.stop()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0, 0.5, 0, -0.5)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 28))
        p.drawRoundedRect(r, 2.5, 2.5)
        w = r.width() * 0.38
        x = -w + (r.width() + w) * (0.5 - 0.5 * math.cos(math.pi * self._t))   # eases in and out
        grad = QLinearGradient(x, 0, x + w, 0)
        grad.setColorAt(0.0, QColor(255, 111, 216, 0))
        grad.setColorAt(0.35, QColor("#ff6fd8"))
        grad.setColorAt(0.75, QColor("#7a5cff"))
        grad.setColorAt(1.0, QColor(122, 92, 255, 0))
        p.setBrush(grad)
        p.drawRoundedRect(QRectF(x, r.top(), w, r.height()), 2.5, 2.5)
        p.end()


class ProfileView(QFrame):
    """Someone at a glance, unfolding right under the person you clicked: their
    two most active repos, their most-starred one, a 30-day activity chart, their
    interests and their links elsewhere. Then, if you like, GitHub to follow."""

    def __init__(self, panel: "MyGeekyPanel", login: str, theme: dict[str, Any]) -> None:
        super().__init__()
        self.login, self.theme, self.panel = login, theme, panel
        self.setObjectName("profileView")
        self.setStyleSheet(f"QFrame#profileView {{ background:{theme['card_bg']}; border:1px solid {theme['accent']}; "
                           f"border-radius:12px; }} QLabel {{ color:{theme['text']}; font-size:11.5px; background:transparent; }}")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(12, 10, 12, 12)
        self.lay.setSpacing(7)
        self.loading = QLabel(f"Looking up <b>{login}</b>\u2026")
        self.loading.setTextFormat(Qt.RichText)
        self.loading.setStyleSheet(f"color:{theme['muted']}; font-size:11px;")
        self.bar = ShimmerBar()
        self.lay.addWidget(self.loading)
        self.lay.addWidget(self.bar)
        self.setMaximumHeight(0)
        self._anim = QPropertyAnimation(self, b"maximumHeight", self)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.finished.connect(self._settled)
        QTimer.singleShot(0, lambda: self._grow_to(self._content_height()))
        panel._run_async(lambda: self._fetch(login), self._show)

    # ---- unfolding
    def _content_height(self) -> int:
        self.lay.activate()
        # height-for-width only counts once something wraps; while loading nothing does
        return max(self.lay.totalHeightForWidth(max(self.width(), 200)), self.lay.totalSizeHint().height())

    def _grow_to(self, h: int, ms: int = 320) -> None:
        self._anim.stop()
        self._anim.setDuration(ms)
        self._anim.setStartValue(self.maximumHeight() if self.maximumHeight() < 16777215 else self.height())
        self._anim.setEndValue(h)
        self._anim.start()

    def _settled(self) -> None:
        if self._anim.endValue() and self._anim.endValue() > 60 and not self.bar.isVisible():
            self.setMaximumHeight(16777215)              # fully open: let it follow its content
            area = self.panel._scroll_area_of(self)
            if area is not None:
                area.ensureWidgetVisible(self, 0, 10)
        elif self._anim.endValue() == 0:
            self.deleteLater()

    def fold(self) -> None:
        """Close it again (it removes itself when folded)."""
        self.setMaximumHeight(self.height())
        self._grow_to(0, 220)

    # ---- content
    @staticmethod
    def _fetch(login: str) -> dict[str, Any]:
        try:
            card = logic.person_card(login)
        except Exception as exc:
            return {"error": str(exc)}
        try:
            import requests
            url = card.get("avatar", "")
            if url.startswith("https://"):
                r = requests.get(url + ("&" if "?" in url else "?") + "s=128", timeout=15)
                card["avatar_bytes"] = r.content if r.ok else b""
        except Exception:
            card["avatar_bytes"] = b""
        return card

    def _muted(self, text: str, size: float = 11) -> QLabel:
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setStyleSheet(f"color:{self.theme['muted']}; font-size:{size}px;")
        return lab

    def _section(self, text: str) -> None:
        lab = QLabel(text)
        lab.setStyleSheet(f"color:{self.theme['muted']}; font-size:9.5px; font-weight:700; letter-spacing:1px; margin-top:4px;")
        self.lay.addWidget(lab)

    def _repo_row(self, r: dict[str, Any], right: str) -> None:
        import html as h
        lab = QLabel(f"<a href='{h.escape(r['url'])}' style='color:{self.theme['text']}; text-decoration:none'>"
                     f"<b>{h.escape(r['name'])}</b></a>"
                     f"<span style='color:{self.theme['muted']}'>  {h.escape(r.get('language') or '')}  {right}</span>"
                     + (f"<br><span style='color:{self.theme['muted']}; font-size:10.5px'>{h.escape(r['description'])}</span>"
                        if r.get("description") else ""))
        lab.setTextFormat(Qt.RichText)
        lab.setWordWrap(True)
        lab.setCursor(Qt.PointingHandCursor)
        lab.linkActivated.connect(lambda url: logic.open_link(url))
        box = QFrame()                              # real margins (CSS padding makes QLabel mis-measure its height)
        box.setObjectName("repoBox")
        box.setStyleSheet("QFrame#repoBox { background:rgba(255,255,255,0.05); border-radius:8px; }")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(9, 6, 9, 6)
        bl.addWidget(lab)
        self.lay.addWidget(box)

    def _show(self, card: dict[str, Any]) -> None:
        import html as h
        self.bar.stop()
        self.bar.hide()
        self.loading.hide()
        top = QHBoxLayout()
        if card.get("error"):
            top.addWidget(self._muted(card["error"]), 1)
            top.addWidget(self._close_btn())
            self.lay.addLayout(top)
            QTimer.singleShot(0, lambda: self._grow_to(self._content_height()))
            return
        pic = QLabel()
        pix = QPixmap()
        if card.get("avatar_bytes") and pix.loadFromData(card["avatar_bytes"]):
            pic.setPixmap(_circular_pixmap(pix, 48))
        pic.setFixedSize(48, 48)
        top.addWidget(pic, 0, Qt.AlignTop)
        names = QVBoxLayout()
        title = QLabel(f"<b style='font-size:14px'>{h.escape(card.get('name') or card['login'])}</b>"
                       + (f"  <span style='color:{self.theme['muted']}'>@{h.escape(card['login'])}</span>"
                          if card.get("name") else ""))
        title.setTextFormat(Qt.RichText)
        names.addWidget(title)
        meta = [m for m in (card.get("location"), card.get("company"),
                            f"{card.get('followers', 0):,} followers", f"{card.get('public_repos', 0)} repos",
                            f"since {card['since']}" if card.get("since") else "") if m]
        names.addWidget(self._muted("  \u00b7  ".join(meta), 10.5))
        top.addLayout(names, 1)
        top.addWidget(self._close_btn(), 0, Qt.AlignTop)
        self.lay.addLayout(top)
        if card.get("bio"):
            self.lay.addWidget(self._muted(card["bio"]))
        if card.get("links"):                          # only the ones they have
            row = QHBoxLayout()
            row.setSpacing(6)
            for link in card["links"]:
                mark, color, name = LINK_MARKS.get(link["kind"], LINK_MARKS["web"])
                b = QPushButton(mark)
                b.setFixedSize(30, 30)
                b.setCursor(Qt.PointingHandCursor)
                b.setToolTip(f"{name}: {link['url']}")
                b.setStyleSheet(f"QPushButton {{ background:{color}; color:white; border:none; border-radius:15px; "
                                f"font-weight:800; font-size:11px; padding:0; }} QPushButton:hover {{ border:2px solid white; }}")
                b.clicked.connect(lambda checked=False, u=link["url"]: QDesktopServices.openUrl(QUrl(u))
                                  if u.startswith("https://") else None)
                row.addWidget(b)
            row.addStretch(1)
            self.lay.addLayout(row)
        if card.get("active"):
            self._section("MOST ACTIVE")
            for r in card["active"]:
                self._repo_row(r, f"pushed {_time_ago(r['pushed_at'])}" if r.get("pushed_at") else "")
        if card.get("top"):
            self._section("MOST STARRED")
            self._repo_row(card["top"], f"\u2605 {card['top']['stars']:,}")
        self._section(f"ACTIVITY, LAST 30 DAYS \u00b7 {sum(card.get('daily') or [])} public events")
        self.lay.addWidget(ActivityChart(card.get("daily") or [], self.theme["accent"]))
        if card.get("interests"):
            self._section("INTERESTS")
            chips = QLabel("".join(f"<span style='background:rgba(122,92,255,0.25); color:{self.theme['text']}'>"
                                   f"&nbsp;{h.escape(t)}&nbsp;</span>&nbsp; " for t in card["interests"]))
            chips.setTextFormat(Qt.RichText)
            chips.setWordWrap(True)
            self.lay.addWidget(chips)
        go = QPushButton("Open on GitHub to follow")
        go.setCursor(Qt.PointingHandCursor)
        go.setStyleSheet("QPushButton { background:#7a5cff; color:white; border:none; border-radius:8px; "
                         "padding:7px 12px; font-weight:700; font-size:11.5px; } QPushButton:hover { background:#8d73ff; }")
        go.clicked.connect(lambda: self.panel._opened_profile(card.get("url", "")))
        self.lay.addSpacing(2)
        self.lay.addWidget(go)
        # unfold to the full card (twice: word-wrapped labels only know their height once styled)
        QTimer.singleShot(0, lambda: self._grow_to(self._content_height(), 420))
        QTimer.singleShot(140, lambda: self._grow_to(self._content_height(), 280))

    def _close_btn(self) -> QPushButton:
        b = QPushButton("\u00d7")
        b.setFixedSize(26, 26)
        b.setCursor(Qt.PointingHandCursor)
        b.setToolTip("Fold it away")
        b.setStyleSheet(f"QPushButton {{ background:transparent; color:{self.theme['muted']}; border:none; font-size:16px; }}"
                        f"QPushButton:hover {{ color:{self.theme['text']}; }}")
        b.clicked.connect(self.panel._fold_profile)
        return b


class IdeaDialog(QDialog):
    """The 💡: an idea, a problem or a question, sent as a prefilled GitHub issue
    that the user submits themselves (nothing is sent from here)."""

    def __init__(self, parent: QWidget, theme: dict[str, Any]) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)   # in front of the always-on-top panel
        from ..ideas import KINDS
        self.setWindowTitle("Send an idea to myGeeKy")
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        intro = QLabel("Ideas, problems and questions go to myGeeKy's maker as a GitHub issue. Your browser opens "
                       "it ready to send. Click <b>Submit</b> there, with your GitHub account. It's public, so "
                       "don't include tokens or private data.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        kinds = QHBoxLayout()
        self.kind_buttons: dict[str, QRadioButton] = {}
        for key, (emoji, label, _) in KINDS.items():
            b = QRadioButton(f"{emoji} {label}")
            self.kind_buttons[key] = b
            kinds.addWidget(b)
        self.kind_buttons["idea"].setChecked(True)
        kinds.addStretch(1)
        lay.addLayout(kinds)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("In a few words")
        lay.addWidget(self.title_edit)
        self.details = QPlainTextEdit()
        self.details.setPlaceholderText("Details: what would help, or what happened and what you expected")
        self.details.setFixedHeight(110)
        lay.addWidget(self.details)
        self.with_version = QCheckBox("Include version info (myGeeKy, Python, Windows version; helps with problems)")
        self.with_version.setChecked(True)
        lay.addWidget(self.with_version)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Close")
        cancel.clicked.connect(self.reject)
        self.send = QPushButton("Open on GitHub ↗")
        self.send.clicked.connect(self._send)
        row.addWidget(cancel)
        row.addWidget(self.send)
        lay.addLayout(row)
        self.setStyleSheet(f"QDialog {{ background:#17171f; }} QLabel, QRadioButton, QCheckBox {{ color:{theme['text']}; "
                           f"font-size:11.5px; }} QLineEdit, QPlainTextEdit {{ background:#22222e; color:{theme['text']}; "
                           f"border:1px solid #34344a; border-radius:7px; padding:5px; }}"
                           f"QPushButton {{ background:{theme['btn_bg']}; color:{theme['text']}; border:none; "
                           f"border-radius:7px; padding:6px 12px; }} QPushButton:hover {{ background:{theme['btn_hover']}; }}"
                           "QRadioButton::indicator { width:12px; height:12px; border-radius:7px; "
                           "border:2px solid #6b6b88; background:transparent; }"
                           f"QRadioButton::indicator:checked {{ background:{theme['accent']}; border-color:{theme['accent']}; }}")

    def kind(self) -> str:
        return next(k for k, b in self.kind_buttons.items() if b.isChecked())

    def _send(self) -> None:
        from ..ideas import issue_url
        if not self.title_edit.text().strip():
            self.status.setText("Give it a short title first.")
            return
        url = issue_url(self.kind(), self.title_edit.text(), self.details.toPlainText(), self.with_version.isChecked())
        QDesktopServices.openUrl(QUrl(url))
        from ..achievements import log
        log("idea")
        self.status.setText("✓ Your browser opened it on GitHub: click <b>Submit new issue</b> there to send it. "
                            "Thank you!")


class IdeaRow(QFrame):
    """One idea/problem/question in the admin inbox; clicking opens it."""

    def __init__(self, item: dict[str, Any], theme: dict[str, Any], on_open: Callable[[str], bool]) -> None:
        super().__init__()
        from ..ideas import KINDS
        self.setObjectName("ideaRow")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(8)
        emoji = QLabel(KINDS.get(item.get("kind", "idea"), KINDS["idea"])[0])
        emoji.setStyleSheet("font-size:14px; background:transparent;")
        lay.addWidget(emoji)
        box = QVBoxLayout()
        box.setSpacing(1)
        title = QLabel(item.get("title", ""))
        title.setTextFormat(Qt.PlainText)
        title.setWordWrap(True)
        title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        title.setStyleSheet(f"color:{theme['text']}; font-size:11.5px; font-weight:600; background:transparent;")
        box.addWidget(title)
        meta = QLabel(f"#{item.get('number')} · {item.get('author', '')} · {_time_ago(item.get('created_at', ''))}"
                      f" · 💬 {item.get('comments', 0)} · 👍 {item.get('reactions', 0)}")
        meta.setTextFormat(Qt.PlainText)
        meta.setStyleSheet(f"color:{theme['muted']}; font-size:10px; background:transparent;")
        box.addWidget(meta)
        lay.addLayout(box, 1)
        self.setStyleSheet(f"QFrame#ideaRow {{ background:{theme['card_bg']}; border-radius:10px; }}"
                           f"QFrame#ideaRow:hover {{ background:{theme['btn_bg']}; }}")
        self.setCursor(Qt.PointingHandCursor)
        url = item.get("url", "")
        self.mousePressEvent = lambda ev: on_open(url)  # noqa: ARG005


class ProspectCard(QFrame):
    """Someone who might want myGeeKy: why, and what you can do. Nothing is
    ever sent from here: Email opens a draft in your mail app, Copy puts the
    invite on your clipboard, and you mark them once you've reached out."""

    def __init__(self, person: dict[str, Any], theme: dict[str, Any], on_action: Callable[[str, dict], None],
                 loader: "AvatarLoader | None" = None) -> None:
        super().__init__()
        self.setObjectName("prospectCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 7, 8, 7)
        outer.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(_avatar_widget(person.get("login", "?"), person.get("avatar", ""), 30, loader))
        box = QVBoxLayout()
        box.setSpacing(1)
        name = QLabel(person.get("name") or person.get("login", ""))
        name.setTextFormat(Qt.PlainText)
        name.setStyleSheet(f"color:{theme['text']}; font-size:12px; font-weight:600; background:transparent;")
        box.addWidget(name)
        why = QLabel(f"@{person.get('login', '')} · " + "; ".join(person.get("why", [])[:2]))
        why.setTextFormat(Qt.PlainText)
        why.setWordWrap(True)
        why.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        why.setStyleSheet(f"color:{theme['muted']}; font-size:10px; background:transparent;")
        box.addWidget(why)
        if person.get("bio"):
            bio = QLabel(person["bio"][:110])
            bio.setTextFormat(Qt.PlainText)
            bio.setWordWrap(True)
            bio.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            bio.setStyleSheet(f"color:{theme['muted']}; font-size:10px; font-style:italic; background:transparent;")
            box.addWidget(bio)
        top.addLayout(box, 1)
        sc = QLabel(f"{person.get('score', 0):.1f}")
        sc.setToolTip("How likely they are to want myGeeKy (higher is better)")
        sc.setStyleSheet(f"color:{theme['accent']}; font-size:12px; font-weight:700; background:transparent;")
        top.addWidget(sc, 0, Qt.AlignTop)
        outer.addLayout(top)
        row = QHBoxLayout()
        row.setSpacing(4)
        style = (f"QPushButton {{ background:{theme['btn_bg']}; color:{theme['text']}; border:none; "
                 f"border-radius:7px; padding:3px 8px; font-size:10.5px; }}"
                 f"QPushButton:hover {{ background:{theme['btn_hover']}; }}")
        actions = [("Profile ↗", "profile"), ("✉ Email" if person.get("email") else "⧉ Copy invite",
                                              "email" if person.get("email") else "copy"),
                   ("Invited ✓", "invited"), ("Not now", "declined")]
        for label, action in actions:
            b = QPushButton(label)
            b.setStyleSheet(style)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda checked=False, a=action: on_action(a, person))
            row.addWidget(b)
        row.addStretch(1)
        outer.addLayout(row)
        self.setStyleSheet(f"QFrame#prospectCard {{ background:{theme['card_bg']}; border-radius:10px; }}")


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
        if item.get("explore"):
            title_row.addWidget(_explore_chip(theme))
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


PANEL_GESTURES = ("thanks", "learn", "watching", "collab")  # "used" needs a repo: CLI only
GESTURE_TIPS = {
    "thanks": "Thank {who} for their work. Private: only they can read it, and no reply is expected.",
    "learn": "Tell {who} you learned from their work. Private, and no reply is expected.",
    "watching": "Let {who} know you're following their work. Private, and no reply is expected.",
    "collab": "Open to collaborating with {who}. They only find out if they choose it for you too; "
              "then you both see it. Otherwise nobody ever knows.",
}


class SignalCard(QFrame):
    """One person on the Signals tab: a signal they sent you, or a fellow
    myGeeKy user. The emoji buttons send a private signal; the arrow opens
    their profile; 🔇 mutes them (they're never told). Everything shown from
    someone's beacon is rendered as plain text."""

    def __init__(self, item: dict[str, Any], theme: dict[str, Any], on_open: Callable[[str], bool],
                 on_send: Callable[["SignalCard", str, str], None] | None,
                 loader: "AvatarLoader | None" = None,
                 on_mute: Callable[[str], None] | None = None) -> None:
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
        badge_text = "🤝 match" if item.get("mutual") else "signalled you" if item.get("signalled_you") else ""
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
            if not item.get("mutual"):
                line += " · no reply needed"
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
        if on_mute is not None and "text" in item:
            mute_btn = QPushButton("🔇")
            mute_btn.setToolTip(f"Mute {self.login}: hide their signals. They're never told; "
                                "`mygeeky beacon unmute` brings them back.")
            mute_btn.setCursor(Qt.PointingHandCursor)
            mute_btn.setFixedSize(24, 24)
            mute_btn.setStyleSheet(btn_style)
            mute_btn.clicked.connect(lambda: on_mute(self.login))
            head.addWidget(mute_btn)
        head.addWidget(profile_btn)
        outer.addLayout(head)

        self.gesture_buttons: dict[str, QPushButton] = {}
        if on_send is not None and item.get("can_receive", True):
            row = QHBoxLayout()
            row.setContentsMargins(38, 0, 0, 0)
            row.setSpacing(4)
            for g in PANEL_GESTURES:
                emoji, verb = GESTURES[g]
                btn = QPushButton(emoji)
                btn.setFixedSize(28, 24)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setToolTip(GESTURE_TIPS[g].format(who=self.login))
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

    def show_result(self, text: str, detail: str = "") -> None:
        self.feedback.setText(text)
        self.feedback.setToolTip(detail)


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
        title_line = QHBoxLayout()
        title_line.setSpacing(5)
        title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        title.setStyleSheet(f"color:{theme['text']}; font-size:11.5px; background:transparent;")
        title.setToolTip(row.get("description", ""))
        title_line.addWidget(title, 1)
        if row.get("paper"):
            title_line.addWidget(published_badge(row["paper"], on_open))
        if row.get("news"):
            title_line.addWidget(news_badge(row["news"], on_open))
        body.addLayout(title_line)

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


class ModelRow(QFrame):
    """One Hugging Face model: name, what it does, likes, downloads, how hot it is."""

    def __init__(self, m: dict[str, Any], theme: dict[str, Any], on_open: Callable[[str], bool]) -> None:
        super().__init__()
        self.setObjectName("modelRow")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(8)
        icon = QLabel("\U0001f917")
        icon.setStyleSheet("font-size:15px; background:transparent;")
        outer.addWidget(icon, 0, Qt.AlignTop)
        body = QVBoxLayout()
        body.setSpacing(1)
        owner, _, name = m.get("id", "").partition("/")
        title = QLabel(f"<b>{html.escape(name)}</b> <span style='color:{theme['muted']}'>{html.escape(owner)}</span>")
        title.setTextFormat(Qt.RichText)
        title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        title.setStyleSheet(f"color:{theme['text']}; font-size:11.5px; background:transparent;")
        body.addWidget(title)
        bits = [m["pipeline"].replace("-", " ")] if m.get("pipeline") else []
        bits += [f"\u2665 {_fmt_count(m.get('likes'))}", f"\u2193 {_fmt_count(m.get('downloads'))}"]
        if m.get("match"):
            bits.append("matches " + ", ".join(m["match"][:3]))
        sub = QLabel(" \u00b7 ".join(bits))
        sub.setTextFormat(Qt.PlainText)
        sub.setWordWrap(True)
        sub.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        sub.setStyleSheet(f"color:{theme['muted']}; font-size:10px; background:transparent;")
        body.addWidget(sub)
        outer.addLayout(body, 1)
        hot = QLabel(f"\U0001f525 {_fmt_count(m.get('trending'))}")
        hot.setToolTip("Hugging Face's trending score: how fast it's gaining likes and downloads right now")
        hot.setStyleSheet(f"color:{theme['text']}; font-size:10.5px; font-weight:600; background:transparent;")
        outer.addWidget(hot, 0, Qt.AlignTop)
        self.setStyleSheet(f"QFrame#modelRow {{ background:{theme['card_bg']}; border-radius:10px; }}"
                           f"QFrame#modelRow:hover {{ background:{theme['btn_bg']}; }}")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(", ".join(m.get("tags") or [])[:300])
        url = m.get("url", "")
        self.mousePressEvent = lambda ev: on_open(url)  # noqa: ARG005


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

        if not post.get("from_feed"):          # the public feed has no vote counts
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
        if item.get("paper"):
            title_row.addWidget(published_badge(item["paper"], on_open))
        if item.get("news"):
            title_row.addWidget(news_badge(item["news"], on_open))
        if item.get("explore"):
            title_row.addWidget(_explore_chip(theme))
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


# name -> (icon, name shown when open / on hover)
TABS = {
    "live": ("\u26a1", "Live"),
    "suggestions": ("\U0001f465", "People"),
    "repos": ("\U0001f4e6", "Repos"),
    "market": ("\U0001f4c8", "Market"),
    "news": ("\U0001f4f0", "News"),
    "activity": ("\U0001f552", "Activity"),
    "signals": ("\U0001f4e1", "Signals"),
    "model": ("\U0001f9e0", "Model"),
    "badges": ("\U0001f3c5", "Badges"),
    "admin": ("\U0001f6e1", "Admin"),
}


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
        self._news_running = False
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
        self._screen_name = ""          # the monitor the panel lives on, remembered across sleep/unplug
        self._dock(folded=False)
        self._watch_screens()
        # the same you on every computer: sync with your private data repo now and then
        self._syncing = False
        self._sync_timer = QTimer(self)
        self._sync_timer.timeout.connect(self._sync_now)
        if logic.sync_enabled(self.cfg):
            QTimer.singleShot(4000, self._sync_now)
            self._sync_timer.start(SYNC_EVERY_MS)

        self._load_status()
        from ..achievements import log_open_today
        log_open_today()                      # a day of use, for the Regular badge
        self._badges: dict[str, Any] = {}
        self._refresh_badges()
        self._load_github_achievements()
        self._load_live_stats()
        self._load_suggestions()
        self._load_contributions()
        self._refresh_activity(force=False)
        self._load_model_history()
        self._load_market()
        self._load_research()
        self._style_market_switch()
        self._load_news()
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

        # news: shown from the cache now, re-fetched in the background when it's due
        self._news_timer = QTimer(self)
        self._news_timer.timeout.connect(self._maybe_refresh_news)
        self._news_timer.start(60 * 60_000)
        QTimer.singleShot(30_000, self._maybe_refresh_news)

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
        self._token_warnings: list[dict[str, Any]] = []
        self._update_timer.timeout.connect(self._check_tokens)
        QTimer.singleShot(10_000, self._check_tokens)

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

        self.idea_btn = QPushButton("\U0001f4a1")
        self.idea_btn.setFixedSize(26, 26)
        self.idea_btn.setCursor(Qt.PointingHandCursor)
        self.idea_btn.setToolTip("Send an idea, a problem or a question to myGeeKy's maker")
        self.idea_btn.clicked.connect(self._open_idea_dialog)
        header.addWidget(self.idea_btn)

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

        self.token_banner = self._build_token_banner()
        self.token_banner.setVisible(False)
        panel_layout.addWidget(self.token_banner)

        self.status_label = QLabel("Loading…")
        self.status_label.setWordWrap(True)
        panel_layout.addWidget(self.status_label)
        self.badge_strip = QFrame()
        self.badge_strip.setCursor(Qt.PointingHandCursor)
        self.badge_strip.setToolTip("Your badges: click to see them all")
        self.badge_strip_layout = QHBoxLayout(self.badge_strip)
        self.badge_strip_layout.setContentsMargins(0, 0, 0, 0)
        self.badge_strip_layout.setSpacing(4)
        self.badge_strip.mousePressEvent = lambda ev: self._switch_tab("badges")  # noqa: ARG005
        panel_layout.addWidget(self.badge_strip)

        self.tab_buttons: dict[str, QPushButton] = {}
        self._is_admin = logic.is_admin(self.cfg)
        tabs = [name for name in TABS if name != "admin" or self._is_admin]
        self._badges_new = False
        for name in tabs:
            btn = PlanetButton(*PLANETS[name])
            btn.setToolTip(TABS[name][1])
            btn.setAccessibleName(TABS[name][1])
            # Qt's Windows style gives every push button a ~75px minimum width;
            # five of those made the panel wider than gui_expanded_width.
            btn.setMinimumWidth(1)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, n=name: self._switch_tab(n))
            self.tab_buttons[name] = btn
        # The dock: every tab is a planet; the open one swells into the selected
        # planet (hover any planet for its name).
        self.tab_bar = QFrame()
        self.tab_bar.setObjectName("tabBar")
        bar = QHBoxLayout(self.tab_bar)
        bar.setContentsMargins(3, 3, 3, 3)
        bar.setSpacing(1)
        for name in tabs:
            bar.addWidget(self.tab_buttons[name], 1)
        panel_layout.addWidget(self.tab_bar)

        self.content_stack = QStackedWidget()
        panel_layout.addWidget(self.content_stack, 1)
        self.height_grip = HeightGrip(self._resize_from_grip, lambda: self.cfg.gui_panel_height_fraction)
        panel_layout.addWidget(self.height_grip, 0, Qt.AlignHCenter)

        self._tab_order = ["live", "suggestions", "repos", "market", "news", "activity", "signals", "model"]
        self.content_stack.addWidget(self._build_live_tab())
        self.content_stack.addWidget(self._build_suggestions_tab())
        self.content_stack.addWidget(self._build_repos_tab())
        self.content_stack.addWidget(self._build_market_tab())
        self.content_stack.addWidget(self._build_news_tab())
        self.content_stack.addWidget(self._build_activity_tab())
        self.content_stack.addWidget(self._build_signals_tab())
        self.content_stack.addWidget(self._build_model_tab())
        self._tab_order.append("badges")
        self.content_stack.addWidget(self._build_badges_tab())
        if self._is_admin:
            self._tab_order.append("admin")
            self.content_stack.addWidget(self._build_admin_tab())

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
        hint = QLabel("Click someone to see their card; follow them on GitHub from there (you always follow by hand).")
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

    def _build_market_tab(self) -> QWidget:
        """Your field's pulse, two ways: repos ranked by momentum, and research
        trends (rising papers, tools with papers, people behind them)."""
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 4, 0, 0)
        outer.setSpacing(6)
        switch = QHBoxLayout()
        switch.setSpacing(4)
        self.market_mode_buttons: dict[str, QPushButton] = {}
        for mode, label in (("repos", "Repos"), ("research", "Research"), ("models", "\U0001f917 Models")):
            b = QPushButton(label)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda checked=False, m=mode: self._set_market_mode(m))
            self.market_mode_buttons[mode] = b
            switch.addWidget(b)
        switch.addStretch(1)
        outer.addLayout(switch)
        self.market_stack = QStackedWidget()
        self.market_stack.addWidget(self._build_market_repos())
        self.market_stack.addWidget(self._build_research_view())
        self.market_stack.addWidget(self._build_models_view())
        outer.addWidget(self.market_stack, 1)
        self._market_mode = "repos"
        return container

    def _set_market_mode(self, mode: str) -> None:
        self._market_mode = mode
        self.market_stack.setCurrentIndex({"repos": 0, "research": 1, "models": 2}[mode])
        self._style_market_switch()
        if mode == "research" and logic.trends_due(self.cfg):
            self._refresh_research(force=False)
        if mode == "models":
            self._render_models(logic.get_hf_models(self.cfg))
            if logic.hf_models_due(self.cfg):
                self._refresh_models(force=False)

    def _style_market_switch(self) -> None:
        theme = THEMES[self._theme_name()]
        for mode, b in self.market_mode_buttons.items():
            active = mode == getattr(self, "_market_mode", "repos")
            b.setStyleSheet(f"QPushButton {{ background:{theme['tab_active'] if active else theme['card_bg']}; "
                            f"color:{theme['text']}; border:none; border-radius:8px; padding:4px 12px; "
                            f"font-size:11px; font-weight:{'700' if active else '400'}; }}")

    # ------------------------------------------------------------------ Hugging Face models
    def _build_models_view(self) -> QScrollArea:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 4, 0)
        actions = QHBoxLayout()
        self.models_updated_label = QLabel("")
        self.refresh_models_btn = QPushButton("Refresh")
        self.refresh_models_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_models_btn.clicked.connect(lambda: self._refresh_models(force=True))
        actions.addWidget(self.models_updated_label, 1)
        actions.addWidget(self.refresh_models_btn)
        layout.addLayout(actions)
        self.models_hint = QLabel("Models trending on Hugging Face: first the ones in your field (from your "
                                  "interests), then the big picture. Click one to open it.")
        self.models_hint.setWordWrap(True)
        layout.addWidget(self.models_hint)
        box = QWidget()
        self.models_area = QVBoxLayout(box)
        self.models_area.setContentsMargins(0, 0, 0, 0)
        self.models_area.setSpacing(5)
        layout.addWidget(box)
        layout.addStretch(1)
        self._models_running = False
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background:transparent; border:none;")
        scroll.viewport().setAutoFillBackground(False)
        page.setAutoFillBackground(False)
        return scroll

    def _refresh_models(self, force: bool) -> None:
        if self._models_running:
            return
        self._models_running = True
        self.refresh_models_btn.setEnabled(False)
        self.models_updated_label.setText("updating\u2026")
        self._run_async(lambda: logic.refresh_hf_models(self.cfg, force=force), self._on_models_ready)

    def _on_models_ready(self, data: Any) -> None:
        self._models_running = False
        self.refresh_models_btn.setEnabled(True)
        self._render_models(data if isinstance(data, dict) else {})

    def _render_models(self, data: dict[str, Any]) -> None:
        theme = THEMES[self._theme_name()]
        _clear_layout(self.models_area)
        muted = f"color:{theme['muted']}; font-size:10.5px; background:transparent;"
        for lbl in (self.models_hint, self.models_updated_label):
            lbl.setStyleSheet(muted)
        self.refresh_models_btn.setStyleSheet(
            f"QPushButton {{ background:{theme['section_btn']}; color:{theme['text']}; border:none; "
            f"border-radius:8px; padding:6px 10px; font-size:11.5px; }}")
        if not self._models_running:
            updated = data.get("updated_at")
            self.models_updated_label.setText(data.get("error") or ("updated " + _time_ago(updated) if updated else ""))
        field, trending = data.get("field") or [], data.get("trending") or []
        if not field and not trending:
            msg = QLabel("No models yet. They load in the background (or click Refresh).")
            msg.setStyleSheet(muted)
            self.models_area.addWidget(msg)
            return
        tags = ", ".join(data.get("tags") or [])
        for label, group in ((f"IN YOUR FIELD" + (f" · {tags}" if tags else ""), field),
                             ("\U0001f30d TRENDING EVERYWHERE", trending)):
            if not group:
                continue
            head = QLabel(label)
            head.setWordWrap(True)
            head.setStyleSheet(f"color:{theme['text']}; font-size:10px; font-weight:700; letter-spacing:0.5px; "
                               "margin-top:6px; background:transparent;")
            self.models_area.addWidget(head)
            for m in group:
                self.models_area.addWidget(ModelRow(m, theme, self._opener("model", m)))

    def _build_research_view(self) -> QScrollArea:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 4, 0)
        actions_row = QHBoxLayout()
        self.research_updated_label = QLabel("")
        self.refresh_research_btn = QPushButton("Refresh")
        self.refresh_research_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_research_btn.clicked.connect(lambda: self._refresh_research(force=True))
        actions_row.addWidget(self.research_updated_label, 1)
        actions_row.addWidget(self.refresh_research_btn)
        layout.addLayout(actions_row)
        self.research_hint = QLabel("")
        self.research_hint.setWordWrap(True)
        layout.addWidget(self.research_hint)
        container = QWidget()
        self.research_area = QVBoxLayout(container)
        self.research_area.setContentsMargins(0, 0, 0, 0)
        self.research_area.setSpacing(6)
        layout.addWidget(container)
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

    def _build_market_repos(self) -> QScrollArea:
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

    def _build_news_tab(self) -> QScrollArea:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 4, 0)
        actions_row = QHBoxLayout()
        self.news_updated_label = QLabel("")
        self.refresh_news_btn = QPushButton("Refresh")
        self.refresh_news_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_news_btn.clicked.connect(lambda: self._refresh_news(force=True))
        actions_row.addWidget(self.news_updated_label, 1)
        actions_row.addWidget(self.refresh_news_btn)
        layout.addLayout(actions_row)
        mode_row = QHBoxLayout()
        mode_row.setSpacing(4)
        self.news_mode_buttons: dict[str, QPushButton] = {}
        for mode, label in (("headlines", "Headlines"), ("papers", "Papers && discussions")):
            b = QPushButton(label)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda checked=False, m=mode: self._set_news_mode(m))
            self.news_mode_buttons[mode] = b
            mode_row.addWidget(b)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)
        self.news_hint = QLabel("")
        self.news_hint.setWordWrap(True)
        self.news_hint.setTextFormat(Qt.RichText)
        layout.addWidget(self.news_hint)
        headlines_box = QWidget()
        self.headlines_area = QVBoxLayout(headlines_box)
        self.headlines_area.setContentsMargins(0, 0, 0, 0)
        self.headlines_area.setSpacing(1)
        layout.addWidget(headlines_box)
        self.headlines_box = headlines_box
        container = QWidget()
        self.news_area = QVBoxLayout(container)
        self.news_area.setContentsMargins(0, 0, 0, 0)
        self.news_area.setSpacing(6)
        layout.addWidget(container)
        self.news_box = container
        self._news_mode = "headlines"
        QTimer.singleShot(0, lambda: self._set_news_mode("headlines"))
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
        self.signals_quiet = QCheckBox("🔕 Not taking signals right now")
        self.signals_quiet.setToolTip("Others can't send you signals while this is on. Nobody is told why, "
                                      "and anything already sent waits for you.")
        self.signals_quiet.setChecked(self.cfg.beacon_quiet)
        self.signals_quiet.toggled.connect(self._on_quiet_toggled)
        layout.addWidget(self.signals_quiet)

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

    def _build_token_banner(self) -> QFrame:
        banner = QFrame()
        banner.setObjectName("tokenBanner")
        layout = QVBoxLayout(banner)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        self.token_label = QLabel("")
        self.token_label.setWordWrap(True)
        layout.addWidget(self.token_label)
        row = QHBoxLayout()
        row.setSpacing(6)
        renew = QPushButton("Renew on GitHub ↗")
        renew.setCursor(Qt.PointingHandCursor)
        from ..tokens import SETTINGS_URL
        renew.clicked.connect(lambda: logic.open_link(SETTINGS_URL))
        self.paste_token_btn = QPushButton("Paste new token")
        self.paste_token_btn.setCursor(Qt.PointingHandCursor)
        self.paste_token_btn.clicked.connect(self._on_paste_token)
        row.addWidget(renew)
        row.addWidget(self.paste_token_btn)
        row.addStretch(1)
        layout.addLayout(row)
        return banner

    def _check_tokens(self) -> None:
        self._run_async(lambda: logic.get_token_warnings(self.cfg), self._on_token_warnings)

    def _on_token_warnings(self, warnings: Any) -> None:
        self._token_warnings = warnings if isinstance(warnings, list) else []
        if not self._token_warnings:
            self.token_banner.setVisible(False)
            return
        lines = [w["message"].split(" Renew it")[0].split(" Make a new")[0] for w in self._token_warnings]
        lines.append("On GitHub, open the token and click 'Regenerate token', then paste it here.")
        self.token_label.setText("\n".join(("⏳ " + ln) if i < len(lines) - 1 else ln for i, ln in enumerate(lines)))
        self.token_banner.setVisible(True)

    def _on_paste_token(self) -> None:
        from PySide6.QtWidgets import QInputDialog, QLineEdit
        if not self._token_warnings:
            return
        target = self._token_warnings[0]
        value, ok = QInputDialog.getText(self, "myGeeKy", f"Paste your new {target['label']}:",
                                         QLineEdit.Password)
        if not ok or not value.strip():
            return
        self.paste_token_btn.setEnabled(False)
        self.token_label.setText("Checking the new token…")
        self._run_async(lambda: logic.replace_token(self.cfg, target["name"], value), self._on_token_replaced)

    def _on_token_replaced(self, result: Any) -> None:
        self.paste_token_btn.setEnabled(True)
        result = result if isinstance(result, dict) else {"ok": False, "message": str(result)}
        self.token_label.setText(("✓ " if result.get("ok") else "✗ ") + result.get("message", ""))
        if result.get("ok"):
            QTimer.singleShot(2500, self._check_tokens)   # another token still due? else the banner goes

    # ------------------------------------------------------------------ 💡 ideas
    def _open_idea_dialog(self) -> None:
        IdeaDialog(self, THEMES[self._theme_name()]).exec()

    # ------------------------------------------------------------------ 🛡 admin (the maker only)
    def _build_admin_tab(self) -> QScrollArea:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 4, 4)
        layout.setSpacing(8)
        actions = QHBoxLayout()
        self.admin_updated = QLabel("")
        self.admin_refresh_btn = QPushButton("Refresh")
        self.admin_refresh_btn.setCursor(Qt.PointingHandCursor)
        self.admin_refresh_btn.clicked.connect(self._refresh_admin)
        actions.addWidget(self.admin_updated, 1)
        actions.addWidget(self.admin_refresh_btn)
        layout.addLayout(actions)
        self.admin_headers = [QLabel("\U0001f4c8 ADOPTION"), QLabel("\U0001f4ec IDEAS INBOX"),
                              QLabel("\U0001f3af PEOPLE TO INVITE")]
        layout.addWidget(self.admin_headers[0])
        tiles = QHBoxLayout()
        tiles.setSpacing(6)
        self.admin_tiles = {k: StatTile(c) for k, c in (("pypi_week", "PyPI / week"), ("installer_downloads", "installs (.exe)"),
                                                        ("stars", "stars"), ("signals_users", "on Signals"))}
        for t in self.admin_tiles.values():
            tiles.addWidget(t, 1)
        layout.addLayout(tiles)
        self.admin_funnel = QLabel("")
        self.admin_funnel.setWordWrap(True)
        layout.addWidget(self.admin_funnel)
        layout.addWidget(self.admin_headers[1])
        inbox_box = QWidget()
        self.admin_inbox = QVBoxLayout(inbox_box)
        self.admin_inbox.setContentsMargins(0, 0, 0, 0)
        self.admin_inbox.setSpacing(5)
        layout.addWidget(inbox_box)
        layout.addWidget(self.admin_headers[2])
        self.admin_hint = QLabel("Ranked by how likely they are to want myGeeKy. Nothing is ever sent from here: "
                                 "Email opens a draft in your mail app, Copy puts the invite on your clipboard. "
                                 "Mark them once you've reached out (10 a day, at most).")
        self.admin_hint.setWordWrap(True)
        layout.addWidget(self.admin_hint)
        prospect_box = QWidget()
        self.admin_prospects = QVBoxLayout(prospect_box)
        self.admin_prospects.setContentsMargins(0, 0, 0, 0)
        self.admin_prospects.setSpacing(6)
        layout.addWidget(prospect_box)
        self.admin_kw_header = QLabel("\U0001f524 KEYWORDS TO TEACH")
        layout.addWidget(self.admin_kw_header)
        self.admin_kw = QLabel("")
        self.admin_kw.setWordWrap(True)
        self.admin_kw.setTextFormat(Qt.RichText)
        layout.addWidget(self.admin_kw)
        layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background:transparent; border:none;")
        scroll.viewport().setAutoFillBackground(False)
        page.setAutoFillBackground(False)
        QTimer.singleShot(0, self._render_admin)
        return scroll

    def _render_admin(self, data: dict[str, Any] | None = None) -> None:
        theme = THEMES[self._theme_name()]
        data = data or logic.admin_data(self.cfg)
        adoption = data.get("adoption") or {}
        for key, tile in self.admin_tiles.items():
            v = adoption.get(key)
            tile.set_value(v or 0, (lambda x: "\u2013") if v is None else None)
            tile.apply_theme(theme)
        f = data.get("funnel") or {}
        self.admin_funnel.setText(f"Invites: {f.get('invited', 0)} sent · {f.get('joined', 0)} joined"
                                  + (f" ({round(100 * f['joined'] / f['invited'])}%)" if f.get("invited") else "")
                                  + f" · {f.get('new', 0)} to consider · {data.get('invited_today', 0)}/10 today")
        _clear_layout(self.admin_inbox)
        inbox = data.get("inbox") or []
        if not inbox:
            empty = QLabel("No ideas yet. They arrive from the \U0001f4a1 button in everyone's panel.")
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color:{theme['muted']}; font-size:10.5px; background:transparent;")
            self.admin_inbox.addWidget(empty)
        for item in inbox[:15]:
            self.admin_inbox.addWidget(IdeaRow(item, theme, logic.open_link))
        _clear_layout(self.admin_prospects)
        people = data.get("prospects") or []
        if not people:
            empty = QLabel("No prospects yet: click Refresh.")
            empty.setStyleSheet(f"color:{theme['muted']}; font-size:10.5px; background:transparent;")
            self.admin_prospects.addWidget(empty)
        for person in people[:25]:
            self.admin_prospects.addWidget(ProspectCard(person, theme, self._on_prospect_action, self.avatar_loader))
        updated = data.get("fetched_at")
        if not getattr(self, "_admin_running", False):
            self.admin_updated.setText("updated " + _time_ago(updated) if updated else "")
        rows = data.get("keyword_requests") or []
        if rows:
            listed = " · ".join(
                f"<b>{html.escape(r['word'])}</b> <span style='color:{theme['muted']}'>"
                + (f"{r['people']} on Signals" if r["people"] else "")
                + (", " if r["people"] and r["suggested"] else "")
                + (f"{r['suggested']} suggested" if r["suggested"] else "") + "</span>"
                for r in rows[:30])
            self.admin_kw.setText(f"{listed}<br><span style='color:{theme['muted']}'>Teach them: run "
                                  "<code>mygeeky admin keywords build</code>, then publish a release.</span>")
        else:
            self.admin_kw.setText(f"<span style='color:{theme['muted']}'>No unknown keywords yet. They come "
                                  "from beacons and from the suggest button.</span>")
        self.admin_kw.setStyleSheet(f"color:{theme['text']}; font-size:10.5px; background:transparent;")
        for lbl in self.admin_headers + [self.admin_kw_header]:
            lbl.setStyleSheet(f"color:{theme['text']}; font-size:10.5px; font-weight:700; letter-spacing:0.5px; "
                              "margin-top:6px; background:transparent;")
        for lbl in (self.admin_funnel, self.admin_hint, self.admin_updated):
            lbl.setStyleSheet(f"color:{theme['muted']}; font-size:10.5px; background:transparent;")
        self.admin_refresh_btn.setStyleSheet(
            f"QPushButton {{ background:{theme['section_btn']}; color:{theme['text']}; border:none; "
            f"border-radius:8px; padding:6px 10px; font-size:11.5px; }}")

    def _refresh_admin(self) -> None:
        if getattr(self, "_admin_running", False):
            return
        self._admin_running = True
        self.admin_refresh_btn.setEnabled(False)
        self.admin_updated.setText("updating\u2026 (a minute or two)")
        self._run_async(lambda: logic.admin_refresh(self.cfg), self._on_admin_ready)

    def _on_admin_ready(self, data: Any) -> None:
        self._admin_running = False
        self.admin_refresh_btn.setEnabled(True)
        if isinstance(data, dict) and data.get("error"):
            self.admin_updated.setText(data["error"])
        self._render_admin()

    def _on_prospect_action(self, action: str, person: dict[str, Any]) -> None:
        login = person.get("login", "")
        if action == "profile":
            logic.open_link(f"https://github.com/{login}")
            return
        if action in ("email", "copy"):
            invite = logic.admin_invite(self.cfg, person)
            if action == "email" and invite.get("mailto"):
                QDesktopServices.openUrl(QUrl(invite["mailto"]))
            else:
                QApplication.clipboard().setText(f"{invite['subject']}\n\n{invite['body']}")
                logic.open_link(f"https://github.com/{login}")
                self.admin_updated.setText(f"Invite for {login} copied: paste it wherever you reach them.")
            return
        result = logic.admin_mark(login, action)
        if not result.get("ok"):
            self.admin_updated.setText(result.get("message", ""))
        self._render_admin()

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

        height_row = QHBoxLayout()
        height_label = QLabel("Panel height")
        height_label.setStyleSheet("font-size:11px; font-weight:600; background:transparent;")
        self.height_value_label = QLabel("")
        self.height_value_label.setStyleSheet("font-size:10.5px; background:transparent;")
        height_row.addWidget(height_label)
        height_row.addStretch(1)
        height_row.addWidget(self.height_value_label)
        layout.addLayout(height_row)
        self.height_slider = QSlider(Qt.Horizontal)
        self.height_slider.setRange(int(logic.MIN_PANEL_HEIGHT * 100), int(logic.MAX_PANEL_HEIGHT * 100))
        self.height_slider.setCursor(Qt.PointingHandCursor)
        self.height_slider.setToolTip("How much of the screen's height the open panel takes "
                                      "(you can also drag its bottom edge)")
        self.height_slider.setValue(int(round(logic.clamp_panel_height(self.cfg.gui_panel_height_fraction) * 100)))
        self.height_value_label.setText(f"{self.height_slider.value()}% of the screen")
        self.height_slider.valueChanged.connect(self._on_height_preview)
        self.height_slider.sliderReleased.connect(self._on_height_committed)
        layout.addWidget(self.height_slider)

        self.hearts_check = QCheckBox("Floating hearts on the folded icon")
        self.hearts_check.setCursor(Qt.PointingHandCursor)
        self.hearts_check.setChecked(self.cfg.gui_hearts_enabled)
        self.hearts_check.toggled.connect(self._on_hearts_toggled)
        layout.addWidget(self.hearts_check)

        # Your setup: what decides how myGeeKy works for you, at a glance
        self.setup_label = QLabel("")
        self.setup_label.setTextFormat(Qt.RichText)
        self.setup_label.setWordWrap(True)
        layout.addWidget(self.setup_label)
        self.signals_btn = QPushButton("")
        self.signals_btn.setCursor(Qt.PointingHandCursor)
        self.signals_btn.clicked.connect(self._on_signals_switch)
        self.signals_btn.hide()
        layout.addWidget(self.signals_btn)

        self.pair_btn = QPushButton("\U0001f4f1 Connect your phone")
        self.pair_btn.setCursor(Qt.PointingHandCursor)
        self.pair_btn.setToolTip("Show a QR code that sets up the myGeeKy phone app in one scan")
        self.pair_btn.clicked.connect(lambda: PairDialog(self, THEMES[self._theme_name()]).exec())
        layout.addWidget(self.pair_btn)

        bottom = QHBoxLayout()
        self.sync_label = QLabel("")
        self.sync_label.setWordWrap(True)
        bottom.addWidget(self.sync_label, 1)
        self.uninstall_btn = QPushButton("Uninstall\u2026")
        self.uninstall_btn.setCursor(Qt.PointingHandCursor)
        self.uninstall_btn.setToolTip("Remove myGeeKy from this computer (you choose whether to keep your data)")
        self.uninstall_btn.clicked.connect(self._uninstall)
        bottom.addWidget(self.uninstall_btn)
        self.quit_btn = QPushButton("Quit myGeeKy")
        self.quit_btn.setCursor(Qt.PointingHandCursor)
        self.quit_btn.setToolTip("Close the panel. Open it again from your apps menu or `mygeeky gui`.")
        self.quit_btn.clicked.connect(self._quit)
        bottom.addWidget(self.quit_btn)
        layout.addLayout(bottom)

        return panel

    def _quit(self) -> None:
        if logic.sync_enabled(self.cfg) and not self._syncing:
            logic.sync_now(self.cfg)            # take the latest from this computer along
        QApplication.quit()

    # ------------------------------------------------------------------ sync between your computers
    def _sync_now(self) -> None:
        if self._syncing:
            return
        self._syncing = True
        self._run_async(lambda: logic.sync_now(self.cfg), self._on_synced)

    def _on_synced(self, result: Any) -> None:
        self._syncing = False
        result = result if isinstance(result, dict) else {}
        if result.get("skipped"):
            return
        if result.get("error"):
            self.sync_label.setText(f"Sync: {result['error'][:120]}")
            return
        self.sync_label.setText("Synced with your other computers " + datetime.now().strftime("%H:%M"))
        if result.get("changed"):
            self._apply_synced_data()

    def _apply_synced_data(self) -> None:
        """Another computer's changes arrived: use its settings and data here too."""
        from dataclasses import fields
        from ..config import load_config
        fresh = load_config()
        for f in fields(fresh):
            setattr(self.cfg, f.name, getattr(fresh, f.name))
        self._apply_theme()
        self._dock(self.folded_widget.isVisible())
        self._load_suggestions()
        if not self._contrib_running:
            self._load_contributions()
        self._render_brain()
        self._refresh_signals(force=False)

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

    def _uninstall(self) -> None:
        """⚙ → Uninstall: opens the step-by-step uninstall wizard. The panel stays
        open until you confirm there (cancelling changes nothing)."""
        exe = sys.executable
        if exe.lower().endswith("python.exe") and os.path.exists(exe[:-len("python.exe")] + "pythonw.exe"):
            exe = exe[:-len("python.exe")] + "pythonw.exe"
        from .. import winproc
        winproc.popen([exe, "-m", "mygeeky.gui.uninstall_wizard"],
                      creationflags=0x00000008 if sys.platform == "win32" else 0, close_fds=True,
                      **({} if sys.platform == "win32" else {"start_new_session": True}))

    def _toggle_settings(self) -> None:
        self.settings_panel.setVisible(not self.settings_panel.isVisible())
        if self.settings_panel.isVisible():
            self._load_setup()

    # ------------------------------------------------------------------ your setup (in ⚙)
    def _load_setup(self) -> None:
        if not getattr(self, "_setup", None):
            self.setup_label.setText("Checking your setup\u2026")
        self._run_async(lambda: logic.setup_overview(self.cfg), self._render_setup)

    def _render_setup(self, info: dict[str, Any]) -> None:
        import html as h
        self._setup = info
        theme = THEMES[self._theme_name()]
        ok, off = "#34d399", theme["muted"]

        def row(name: str, value: str, color: str | None = None) -> str:
            return (f"<tr><td style='color:{theme['muted']}; padding:1px 10px 1px 0'>{name}</td>"
                    f"<td style='color:{color or theme['text']}'>{value}</td></tr>")
        rows = [row("GitHub", h.escape(info.get("user") or "not set"))]
        for t in info.get("tokens", []):
            label = "Token 1 (read)" if t["name"] == "read" else "Token 2 (Signals)" if t["name"] == "beacon" else t["name"]
            msg = t["message"].split(") ", 1)[-1] if ") " in t["message"] else t["message"]
            bad = t["state"] in ("expired", "invalid", "soon")
            rows.append(row(label, h.escape(msg or "stored"), "#f87171" if bad else None))
        if info.get("signals"):
            rows.append(row("Signals", "\u2713 on: you send and receive", ok))
        else:
            rows.append(row("Signals", "off" + ("" if info.get("beacon_token") else " (needs token 2)"), off))
        rows.append(row("Sync", f"\u2713 on: {h.escape(info['sync'])}" if info.get("sync") else "off: this computer only",
                        ok if info.get("sync") else off))
        rows.append(row("ORCID", h.escape(info.get("orcid") or "not set"), None if info.get("orcid") else off))
        rows.append(row("Scholar", h.escape(info.get("scholar") or "not set"), None if info.get("scholar") else off))
        rows.append(row("CV", h.escape(info.get("cv") or "not set"), None if info.get("cv") else off))
        kws = info.get("keywords") or []
        rows.append(row("Keywords", h.escape(", ".join(kws[:6]) + ("\u2026" if len(kws) > 6 else "")) if kws
                        else "none yet (add them in the Model tab)", None if kws else off))
        rows.append(row("Version", h.escape(info.get("version", ""))))
        self.setup_label.setText(
            f"<div style='font-size:11px; font-weight:600; color:{theme['text']}; margin-bottom:4px'>Your setup</div>"
            f"<table style='font-size:10.5px'>{''.join(rows)}</table>")
        self.setup_label.setStyleSheet("background:transparent;")
        can = info.get("signals") or info.get("beacon_token")
        self.signals_btn.setVisible(bool(can))
        self.signals_btn.setEnabled(True)
        self.signals_btn.setText("Turn Signals off" if info.get("signals") else "Turn Signals on")
        self.signals_btn.setStyleSheet(
            f"QPushButton {{ background:{theme['btn_bg']}; color:{theme['text']}; border:none; border-radius:7px; "
            f"padding:4px 10px; font-size:11px; }} QPushButton:hover {{ background:{theme['btn_hover']}; }}")

    def _on_signals_switch(self) -> None:
        on = not self.cfg.beacon_enabled
        self.signals_btn.setEnabled(False)
        self.signals_btn.setText("Turning Signals on\u2026" if on else "Turning Signals off\u2026")

        def done(result: dict[str, Any]) -> None:
            if not result.get("ok"):
                self.setup_label.setText(self.setup_label.text() + f"<p style='color:#f87171; font-size:10.5px'>"
                                         f"Couldn't turn Signals on: {result.get('error')}</p>")
            self._refresh_signals(force=True)
            self._load_setup()
        self._run_async(lambda: logic.set_signals_enabled(self.cfg, on), done)

    @staticmethod
    def _slider_to_opacity(value: int) -> float:
        return 1.0 - (value / 100.0)

    @staticmethod
    def _opacity_to_slider(opacity: float) -> int:
        return int(round((1.0 - opacity) * 100))

    # ------------------------------------------------------------------ panel height
    def _on_height_preview(self, value: int) -> None:
        """Live while dragging the slider; saved on release."""
        self.cfg.gui_panel_height_fraction = logic.clamp_panel_height(value / 100)
        self.height_value_label.setText(f"{value}% of the screen")
        if not self.folded_widget.isVisible():
            self._dock(folded=False)

    def _on_height_committed(self) -> None:
        logic.set_panel_height(self.cfg, self.height_slider.value() / 100)

    def _resize_from_grip(self, dy: float, start_fraction: float, done: bool) -> None:
        """The bottom-edge grip: the panel is centred on the screen edge, so it grows
        at the top and the bottom alike -- twice the drag, as a share of the screen."""
        screen_h = max(self._home_screen().availableGeometry().height(), 1)
        fraction = logic.clamp_panel_height(start_fraction + 2 * dy / screen_h)
        self.cfg.gui_panel_height_fraction = fraction
        self._dock(folded=False)
        if hasattr(self, "height_slider"):
            self.height_slider.blockSignals(True)
            self.height_slider.setValue(int(round(fraction * 100)))
            self.height_slider.blockSignals(False)
            self.height_value_label.setText(f"{int(round(fraction * 100))}% of the screen")
        if done:
            logic.set_panel_height(self.cfg, fraction)

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

        self.brain_title = QLabel("What myGeeKy knows about you")
        layout.addWidget(self.brain_title)
        self.brain_intro = QLabel("")
        self.brain_intro.setWordWrap(True)
        layout.addWidget(self.brain_intro)

        self.map_header = QLabel("\U0001f9ed YOUR INTEREST MAP")
        layout.addWidget(self.map_header)
        self.interest_map = InterestMap()
        layout.addWidget(self.interest_map)
        self.map_legend = QLabel("")
        self.map_legend.setWordWrap(True)
        self.map_legend.setTextFormat(Qt.RichText)
        layout.addWidget(self.map_legend)

        # your keywords: green ones mean something to the model, red ones are plain words for now
        self.kw_header = QLabel("\U0001f524 YOUR KEYWORDS")
        layout.addWidget(self.kw_header)
        self.kw_chips = QLabel("")
        self.kw_chips.setWordWrap(True)
        self.kw_chips.setTextFormat(Qt.RichText)
        self.kw_chips.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        self.kw_chips.linkActivated.connect(self._on_keyword_link)
        self.kw_chips.linkHovered.connect(self._on_keyword_hover)
        layout.addWidget(self.kw_chips)
        kw_row = QHBoxLayout()
        kw_row.setSpacing(6)
        self.kw_input = QLineEdit()
        self.kw_input.setPlaceholderText("Add a keyword: AI, single cell, GWAS…")
        self.kw_input.returnPressed.connect(self._on_add_keyword)
        self.kw_completer = QCompleter([])
        self.kw_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.kw_completer.setFilterMode(Qt.MatchContains)
        self.kw_input.setCompleter(self.kw_completer)
        self.kw_add = QPushButton("Add")
        self.kw_add.setCursor(Qt.PointingHandCursor)
        self.kw_add.clicked.connect(self._on_add_keyword)
        kw_row.addWidget(self.kw_input, 1)
        kw_row.addWidget(self.kw_add)
        layout.addLayout(kw_row)
        self.kw_detail = QLabel("")
        self.kw_detail.setWordWrap(True)
        layout.addWidget(self.kw_detail)

        self.teach_header = QLabel("\U0001f9e0 WHAT TEACHES IT (LAST 30 DAYS)")
        layout.addWidget(self.teach_header)
        teach = QHBoxLayout()
        teach.setSpacing(6)
        self.teach_tiles = {key: StatTile(caption) for key, caption in (
            ("clicks", "clicks"), ("follows", "follows"), ("stars", "stars"), ("forks", "forks"))}
        for tile in self.teach_tiles.values():
            teach.addWidget(tile, 1)
        layout.addLayout(teach)
        self.teach_hint = QLabel("")
        self.teach_hint.setWordWrap(True)
        layout.addWidget(self.teach_hint)

        self.explore_header = QLabel("\U0001f52d ROOM TO EXPLORE")
        layout.addWidget(self.explore_header)
        explore_row = QHBoxLayout()
        explore_row.setSpacing(10)
        self.explore_donut = ExploreDonut()
        explore_row.addWidget(self.explore_donut)
        self.explore_label = QLabel("")
        self.explore_label.setWordWrap(True)
        explore_row.addWidget(self.explore_label, 1)
        layout.addLayout(explore_row)

        self.followback_header = QLabel("\U0001f465 WHO FOLLOWS YOU BACK")
        layout.addWidget(self.followback_header)
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
        self.token_banner.setStyleSheet(
            f"QFrame#tokenBanner {{ background:rgba(255,196,87,40); border:1px solid rgba(255,196,87,120); "
            f"border-radius:10px; }}"
            f"QLabel {{ color:{theme['text']}; font-size:11px; background:transparent; }}"
            f"QPushButton {{ background:{theme['btn_bg']}; color:{theme['text']}; border:none; "
            f"border-radius:7px; padding:4px 9px; font-size:11px; }}"
            f"QPushButton:hover {{ background:{theme['btn_hover']}; }}")
        self.activity_updated_label.setStyleSheet(f"color:{theme['muted']}; font-size:11px; background:transparent;")

        for lbl in (self.stat_friends_label, self.stat_new_label, self.stat_rate_label):
            lbl.setStyleSheet(f"font-size:11px; font-weight:600; color:{theme['text']}; background:transparent;")
        self.ticker.set_theme(theme)

        self.fold_btn.setStyleSheet(
            f"QPushButton {{ background:{theme['btn_bg']}; color:{theme['text']}; border:none; "
            f"border-radius:8px; font-size:14px; }}"
            f"QPushButton:hover {{ background:{theme['btn_hover']}; }}"
        )
        for btn in (self.settings_btn, self.idea_btn):
            btn.setStyleSheet(
                f"QPushButton {{ background:{theme['btn_bg']}; color:{theme['text']}; border:none; "
                f"border-radius:8px; font-size:13px; }}"
                f"QPushButton:hover {{ background:{theme['btn_hover']}; }}"
            )
        self.settings_panel.setStyleSheet(f"#settings {{ background:{theme['card_bg']}; border-radius:12px; }}")
        self.opacity_value_label.setStyleSheet(f"font-size:10.5px; color:{theme['muted']}; background:transparent;")
        self.hearts_check.setStyleSheet(f"QCheckBox {{ font-size:11px; color:{theme['text']}; background:transparent; }}")
        self.sync_label.setStyleSheet(f"color:{theme['muted']}; font-size:10px; background:transparent;")
        self.pair_btn.setStyleSheet(f"QPushButton {{ background:{theme['section_btn']}; color:{theme['text']}; "
                                    f"border:none; border-radius:8px; padding:6px 10px; font-size:11.5px; }}"
                                    f"QPushButton:hover {{ background:{theme['btn_hover']}; }}")
        self.uninstall_btn.setStyleSheet(f"QPushButton {{ background:transparent; color:#f87171; border:none; "
                                         f"padding:4px 6px; font-size:11px; }} QPushButton:hover {{ text-decoration:underline; }}")
        self.quit_btn.setStyleSheet(f"QPushButton {{ background:{theme['btn_bg']}; color:{theme['text']}; border:none; "
                                    f"border-radius:7px; padding:4px 10px; font-size:11px; }}"
                                    f"QPushButton:hover {{ background:{theme['btn_hover']}; }}")
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
                    self.refresh_signals_btn, self.refresh_news_btn, self.refresh_research_btn):
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
        self.tab_bar.setStyleSheet(f"QFrame#tabBar {{ background:{theme['card_bg']}; border-radius:10px; }}")
        dark = _parse_color(theme["text"], force_alpha=255).lightness() > 128
        for name, btn in self.tab_buttons.items():
            active = name == self.active_tab
            icon, label = TABS[name]
            new_badge = name == "badges" and self._badges_new
            # the text isn't drawn (the planet is): it's for screen readers and the tests
            btn.setText(f"{icon}  {label}" if active else icon + ("\u2022" if new_badge else ""))
            btn.setStyleSheet("QPushButton { background: transparent; border: none; }")
            btn.set_planet_bg(QColor("#1c1c2c") if dark else QColor("#ffffff"))
            btn.set_dot(new_badge)
            btn.set_selected(active)

    def _on_theme_clicked(self, name: str) -> None:
        if logic.set_theme(self.cfg, name):
            self._apply_theme()
            self._render_brain()
            self._render_suggestions_from_cache()
            self._load_market()
            self._load_news()
            self._set_news_mode(self._news_mode)
            self._render_models(logic.get_hf_models(self.cfg))

    def _render_suggestions_from_cache(self) -> None:
        # Re-render already-loaded cards so their theme-dependent styling updates too.
        self._load_suggestions()
        if not self._contrib_running:  # don't wipe the "Searching…" placeholder mid-search
            self._load_contributions()
        self._refresh_activity(force=False)
        self._refresh_signals(force=False)  # cached unless due: just re-renders

    # ------------------------------------------------------------------ fold/unfold/dock
    def _home_screen(self):
        """The monitor the panel belongs on: the one it was docked to, if it's
        connected (again); otherwise wherever it is now, or the primary one."""
        for screen in QGuiApplication.screens():
            if self._screen_name and screen.name() == self._screen_name:
                return screen
        return self.screen() or QGuiApplication.primaryScreen()

    def _docked_geometry(self, folded: bool, screen) -> QRect:
        rect = screen.availableGeometry()  # excludes the taskbar
        # the folded tab is sized purely by config; the full panel can't go
        # below what its content needs, so position it by that real size
        need = QSize(0, 0) if folded else self.panel_frame.minimumSizeHint()
        return QRect(*logic._panel_geometry(self.cfg, folded, rect, need.width(), need.height()))

    def _dock(self, folded: bool) -> None:
        screen = self._home_screen()
        self._screen_name = screen.name()
        self.panel_frame.setVisible(not folded)
        self.folded_widget.setVisible(folded)
        self.setMinimumSize(0, 0)
        self.setGeometry(self._docked_geometry(folded, screen))
        self.setWindowOpacity(self.cfg.gui_folded_opacity if folded else self.cfg.gui_opacity)

    # The panel has no drag handle: it always belongs docked to its edge (and on
    # top: see topmost.py; the same check puts it back in front). But
    # Windows moves windows on its own -- when a monitor sleeps or is
    # unplugged, the PC locks or resumes, the resolution or scaling changes, a
    # remote-desktop session connects, or Explorer restarts -- and often parks
    # them in the middle of the main screen. So whenever screens change, and
    # every few seconds as a backstop, put it back where it belongs.
    def _watch_screens(self) -> None:
        app = QGuiApplication.instance()
        app.screenAdded.connect(self._on_screen_added)
        app.screenRemoved.connect(lambda s: self._redock_soon())
        app.primaryScreenChanged.connect(lambda s: self._redock_soon())
        for screen in QGuiApplication.screens():
            self._on_screen_added(screen)
        self._dock_guard = QTimer(self)
        self._dock_guard.timeout.connect(self._ensure_docked)
        self._dock_guard.start(DOCK_GUARD_MS)

    def _on_screen_added(self, screen) -> None:
        screen.availableGeometryChanged.connect(lambda r: self._redock_soon())
        screen.geometryChanged.connect(lambda r: self._redock_soon())
        self._redock_soon()

    def _redock_soon(self) -> None:
        # Windows finishes rearranging windows a moment after the screen event
        for delay in (400, 2500):
            QTimer.singleShot(delay, self._ensure_docked)

    def _ensure_docked(self) -> None:
        if not self.isVisible() or self.isMinimized():
            return
        # Windows also drops "always on top" now and then, leaving the icon behind other windows
        from . import topmost
        # our own windows (the QR code, the idea box, a token prompt, the hearts) may
        # sit over the panel: never lift the panel above them
        own = {int(w.winId()) for w in QApplication.topLevelWidgets()
               if w is not self and w.isVisible() and w.isWindow()}
        topmost.keep_on_top(int(self.winId()), ignore=own)
        folded = self.folded_widget.isVisible()
        want = self._docked_geometry(folded, self._home_screen())
        have = self.geometry()
        if abs(have.x() - want.x()) > 2 or abs(have.y() - want.y()) > 2                 or abs(have.width() - want.width()) > 2 or abs(have.height() - want.height()) > 2:
            self._dock(folded)

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
        logic.record_click(self.cfg, "person", item)
        self._open_github(item.get("profile_url", ""))
        logic.mark_suggestion_seen(item.get("username", ""))
        # re-render on the next event-loop turn: the clicked card is still
        # inside its own mousePressEvent right now
        QTimer.singleShot(0, self._load_suggestions)

    def _opener(self, kind: str, item: dict[str, Any]) -> Callable[[str], bool]:
        """open_profile, plus: this click is an interest signal (and counts toward badges)."""
        def open_and_learn(url: str) -> bool:
            logic.record_click(self.cfg, kind, item)
            QTimer.singleShot(0, self._refresh_badges)
            return logic.open_link(url)
        return open_and_learn

    # ------------------------------------------------------------------ badges
    STRIP_MAX = 7

    def _refresh_badges(self) -> None:
        self._badges = logic.get_badges(self.cfg)
        self._render_badge_strip()
        self._update_badge_tab_label()
        if self.active_tab == "badges":
            self._render_badges()

    def _load_github_achievements(self) -> None:
        self._run_async(lambda: logic.refresh_github_achievements(self.cfg), lambda r: self._refresh_badges())

    def _badge_icon(self, b: dict[str, Any], size: int = 22, locked: bool = False) -> QLabel:
        from ..achievements import TIER_COLORS
        icon = QLabel(b["emoji"])
        icon.setFixedSize(size, size)
        icon.setAlignment(Qt.AlignCenter)
        ring = "#55556a" if locked else TIER_COLORS.get(b["tier"], "#55556a")
        icon.setStyleSheet(f"background:{'rgba(255,255,255,0.04)' if locked else 'rgba(255,255,255,0.10)'}; "
                           f"border:2px solid {ring}; border-radius:{size // 2}px; font-size:{int(size * 0.5)}px;")
        return icon

    def _github_icon(self, a: dict[str, str], size: int = 22) -> QLabel:
        icon = QLabel()
        icon.setFixedSize(size, size)
        icon.setToolTip(f"GitHub achievement: {a.get('name', '')}")
        icon.setStyleSheet("background:transparent;")
        self.avatar_loader.request(a.get("image", ""), size, icon.setPixmap)
        return icon

    def _render_badge_strip(self) -> None:
        _clear_layout(self.badge_strip_layout)
        data = getattr(self, "_badges", {})
        mine, github = data.get("earned", []), data.get("github", [])
        shown = 0
        for b in mine:
            if shown >= self.STRIP_MAX:
                break
            icon = self._badge_icon(b)
            icon.setToolTip(f"{b['tier'].capitalize()} {b['name']}: {b['count']} {b['what']}")
            self.badge_strip_layout.addWidget(icon)
            shown += 1
        for a in github:
            if shown >= self.STRIP_MAX:
                break
            self.badge_strip_layout.addWidget(self._github_icon(a))
            shown += 1
        extra = len(mine) + len(github) - shown
        if extra > 0:
            more = QLabel(f"+{extra}")
            more.setStyleSheet(f"color:{THEMES[self._theme_name()]['muted']}; font-size:10.5px; "
                               "font-weight:700; background:transparent;")
            self.badge_strip_layout.addWidget(more)
        self.badge_strip_layout.addStretch(1)
        self.badge_strip.setVisible(bool(mine or github))

    def _update_badge_tab_label(self) -> None:
        seen = set(self.cfg.badges_seen)
        new = [b for b in getattr(self, "_badges", {}).get("earned", []) if f"{b['id']}:{b['tier']}" not in seen]
        btn = self.tab_buttons.get("badges")
        if btn is not None:
            self._badges_new = bool(new)
            self._update_tab_styles()
            btn.setToolTip(f"New badge: {new[0]['emoji']} {new[0]['name']}!" if new else "Your badges")

    def _build_badges_tab(self) -> QScrollArea:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 4, 4)
        layout.setSpacing(8)
        self.badges_title = QLabel("Your badges")
        layout.addWidget(self.badges_title)
        self.badges_intro = QLabel("Earned by using myGeeKy: opening things, following people, coming back. "
                                   "Bronze, then silver, then gold.")
        self.badges_intro.setWordWrap(True)
        layout.addWidget(self.badges_intro)
        box = QWidget()
        self.badges_area = QVBoxLayout(box)
        self.badges_area.setContentsMargins(0, 0, 0, 0)
        self.badges_area.setSpacing(6)
        layout.addWidget(box)
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

    def _render_badges(self) -> None:
        from ..achievements import TIER_COLORS
        theme = THEMES[self._theme_name()]
        _clear_layout(self.badges_area)
        data = getattr(self, "_badges", None) or logic.get_badges(self.cfg)
        self.badges_title.setStyleSheet(f"color:{theme['text']}; font-size:15px; font-weight:700; background:transparent;")
        self.badges_intro.setStyleSheet(f"color:{theme['muted']}; font-size:10.5px; background:transparent;")

        def header(text: str) -> None:
            lbl = QLabel(text)
            lbl.setStyleSheet(f"color:{theme['text']}; font-size:10.5px; font-weight:700; letter-spacing:0.5px; "
                              "margin-top:6px; background:transparent;")
            self.badges_area.addWidget(lbl)

        if data.get("github"):
            header("ON GITHUB")
            row = QHBoxLayout()
            row.setSpacing(10)
            for a in data["github"]:
                cell = QVBoxLayout()
                cell.setSpacing(2)
                cell.addWidget(self._github_icon(a, 44), 0, Qt.AlignHCenter)
                name = QLabel(a.get("name", ""))
                name.setTextFormat(Qt.PlainText)
                name.setStyleSheet(f"color:{theme['muted']}; font-size:9.5px; background:transparent;")
                cell.addWidget(name, 0, Qt.AlignHCenter)
                row.addLayout(cell)
            row.addStretch(1)
            self.badges_area.addLayout(row)

        header("ON MYGEEKY")
        for b in sorted(data.get("all", []), key=lambda b: (-b["level"], b["name"])):
            locked = not b["tier"]
            card = QFrame()
            card.setObjectName("badgeCard")
            lay = QHBoxLayout(card)
            lay.setContentsMargins(8, 6, 8, 6)
            lay.setSpacing(10)
            lay.addWidget(self._badge_icon(b, 36, locked=locked))
            body = QVBoxLayout()
            body.setSpacing(1)
            tier = "" if locked else f"  <span style='color:{TIER_COLORS[b['tier']]}'>{b['tier']}</span>"
            name = QLabel(f"<b>{html.escape(b['name'])}</b>{tier}")
            name.setTextFormat(Qt.RichText)
            name.setStyleSheet(f"color:{theme['text'] if not locked else theme['muted']}; font-size:12px; "
                               "background:transparent;")
            body.addWidget(name)
            if b["single"]:
                status = "earned" if not locked else f"not yet: {b['what']}"
            elif b["next"] is None:
                status = f"{b['count']} {b['what']}: the top level!"
            else:
                status = f"{b['count']} of {b['next']} {b['what']}"
            sub = QLabel(status)
            sub.setTextFormat(Qt.PlainText)
            sub.setWordWrap(True)
            sub.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            sub.setStyleSheet(f"color:{theme['muted']}; font-size:10px; background:transparent;")
            body.addWidget(sub)
            if not b["single"] and b["next"] is not None:
                bar = QProgressBar()
                bar.setRange(0, b["next"])
                bar.setValue(min(b["count"], b["next"]))
                bar.setTextVisible(False)
                bar.setFixedHeight(4)
                bar.setStyleSheet(f"QProgressBar {{ background:rgba(255,255,255,0.08); border:none; border-radius:2px; }}"
                                  f"QProgressBar::chunk {{ background:{theme['accent']}; border-radius:2px; }}")
                body.addWidget(bar)
            lay.addLayout(body, 1)
            card.setStyleSheet(f"QFrame#badgeCard {{ background:{theme['card_bg']}; border-radius:10px; }}")
            self.badges_area.addWidget(card)

    _PROFILE_URL = re.compile(r"^https://github\.com/([A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38})/?$")

    def _open_github(self, url: str, anchor: tuple[QVBoxLayout, QWidget] | None = None) -> bool:
        """A person's profile unfolds their card right under what you clicked;
        repos and everything else open in the browser as before."""
        m = self._PROFILE_URL.match(url or "")
        if not m:
            return logic.open_profile(url)
        login = m.group(1)
        view = getattr(self, "_profile_view", None)
        if view is not None and _alive(view):
            same = view.login.lower() == login.lower()
            view.fold()
            self._profile_view = None
            if same:                                  # a second click on the same person folds it
                return True
        anchor = anchor or self._clicked_item()
        if anchor is None:
            return logic.open_profile(url)
        layout, item = anchor
        view = ProfileView(self, login, THEMES[self._theme_name()])
        layout.insertWidget(layout.indexOf(item) + 1, view)
        self._profile_view = view
        return True

    def _clicked_item(self) -> tuple[QVBoxLayout, QWidget] | None:
        """The list item under the mouse (a card in a scrolling list, or the Live
        spotlight), and the layout it sits in."""
        w = QApplication.widgetAt(QCursor.pos())
        page = self.content_stack.currentWidget()
        fallback = None
        while w is not None and w is not page:
            parent = w.parentWidget()
            lay = parent.layout() if parent is not None else None
            if isinstance(lay, QVBoxLayout) and lay.indexOf(w) >= 0:
                grand = parent.parentWidget()
                if grand is not None and isinstance(grand.parentWidget(), QScrollArea):
                    return lay, w                     # a card in a scrolling list
                if parent is page or (isinstance(page, QScrollArea) and parent is page.widget()):
                    fallback = (lay, w)               # e.g. the Live spotlight
            w = parent
        return fallback

    def _scroll_area_of(self, w: QWidget) -> QScrollArea | None:
        while w is not None:
            if isinstance(w, QScrollArea):
                return w
            w = w.parentWidget()
        return None

    def _fold_profile(self) -> None:
        view = getattr(self, "_profile_view", None)
        if view is not None and _alive(view):
            view.fold()
        self._profile_view = None

    def _opened_profile(self, url: str) -> None:
        """'Open on GitHub to follow' from a card."""
        logic.open_profile(url)
        suggestion = next((s for s in self._last_suggestions if s.get("profile_url") == url), None)
        if suggestion:
            logic.mark_suggestion_seen(suggestion.get("username", ""))
            QTimer.singleShot(0, self._load_suggestions)

    def _on_ticker_clicked(self, url: str) -> bool:
        opened = self._open_github(url)
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
        mentions = logic.news_mentions([i.get("full_name", "") for i in items])
        for item in items:
            item = {**item, "news": mentions.get(item.get("full_name", ""))}
            self.repos_area.addWidget(RepoCard(item, theme, self._opener("repo", item), self.avatar_loader))

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
                card = ActivityGroup(group, theme, self._open_github, self.avatar_loader,
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
        self.signals_quiet.setStyleSheet(f"QCheckBox {{ color:{theme['muted']}; font-size:10.5px; "
                                         "background:transparent; }")
        if not data.get("enabled"):
            self.signals_hint.setText(
                "Send other myGeeKy users small private signals (🙏 📚 👀 🤝) and see theirs to you. "
                "To join, run `mygeeky beacon init` in a terminal.")
            self.refresh_signals_btn.setEnabled(False)
            self.signals_quiet.setVisible(False)
            return
        self.refresh_signals_btn.setEnabled(True)
        self.signals_quiet.setVisible(bool(data.get("can_send")))
        self.signals_quiet.blockSignals(True)
        self.signals_quiet.setChecked(bool(data.get("quiet")))
        self.signals_quiet.blockSignals(False)
        self.signals_hint.setText("🙏 thanks · 📚 learned from you · 👀 following your work · 🤝 open to "
                                  "collaborating (shown only if you both choose it). Signals are private: only "
                                  "the person you send one to can read it, and no reply is ever expected.")
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
        if data.get("quiet"):
            held = data.get("held") or 0
            empty = QLabel("You're not taking signals right now." +
                           (f" {held} signal(s) are waiting for when you're back." if held else ""))
            empty.setWordWrap(True)
            empty.setStyleSheet(muted)
            self.signals_area.addWidget(empty)
        elif not incoming:
            empty = QLabel("Nothing yet. Signals here are small thank-yous: no reply is ever expected.")
            empty.setWordWrap(True)
            empty.setStyleSheet(muted)
            self.signals_area.addWidget(empty)
        for item in incoming:
            self.signals_area.addWidget(SignalCard(item, theme, self._open_github, on_send, self.avatar_loader,
                                                   on_mute=self._on_mute_signals))
        people = data.get("people") or []
        header("FELLOW GEEKS ON MYGEEKY")
        if not people:
            empty = QLabel("No other beacons found yet.")
            empty.setStyleSheet(muted)
            self.signals_area.addWidget(empty)
        for item in people:
            if item.get("muted"):
                continue
            self.signals_area.addWidget(SignalCard(item, theme, self._open_github, on_send, self.avatar_loader))

    def _on_send_signal(self, card: "SignalCard", login: str, gesture: str) -> None:
        card.set_busy(True)
        card.show_result("sending…")

        def done(result: Any) -> None:
            card.set_busy(False)
            ok = isinstance(result, dict) and result.get("ok")
            if ok:
                card.show_result("sent privately ✓")
            else:
                error = (result or {}).get("error", "") if isinstance(result, dict) else ""
                # courtesy limits explain themselves; show the first sentence, the rest on hover
                card.show_result((error.split(". ")[0] or "Not sent")[:60], error)
        self._run_async(lambda: logic.send_signal(self.cfg, login, gesture), done)

    def _on_quiet_toggled(self, quiet: bool) -> None:
        self.signals_quiet.setEnabled(False)

        def done(result: Any) -> None:
            self.signals_quiet.setEnabled(True)
            if not (isinstance(result, dict) and result.get("ok")):
                self.signals_quiet.blockSignals(True)
                self.signals_quiet.setChecked(not quiet)
                self.signals_quiet.blockSignals(False)
                self.signals_updated_label.setText((result or {}).get("error", "Couldn't change it")
                                                   if isinstance(result, dict) else "Couldn't change it")
            self._refresh_signals(force=False)
        self._run_async(lambda: logic.set_signals_quiet(self.cfg, quiet), done)

    def _on_mute_signals(self, login: str) -> None:
        logic.mute_signals(self.cfg, login, True)
        self.signals_updated_label.setText(f"Muted {login}. They're not told.")
        self._refresh_signals(force=False)

    # ------------------------------------------------------------------ market
    NEWS_HINTS = {
        "headlines": "What's happening across your work, as titles: AI labs, journals and the tech press, ranked by "
                     "your interests. \U0001f30d = the big picture.<br>" + BADGE_LEGEND,
        "papers": "New papers and discussions about your interests, from arXiv, bioRxiv and Hacker News. "
                  "\U0001f52d = outside your usual interests, on purpose.<br>" + BADGE_LEGEND,
    }

    def _set_news_mode(self, mode: str) -> None:
        self._news_mode = mode
        self.headlines_box.setVisible(mode == "headlines")
        self.news_box.setVisible(mode == "papers")
        self.news_hint.setText(self.NEWS_HINTS[mode])
        theme = THEMES[self._theme_name()]
        for m, b in self.news_mode_buttons.items():
            active = m == mode
            b.setStyleSheet(f"QPushButton {{ background:{theme['tab_active'] if active else theme['btn_bg']}; "
                            f"color:{theme['text']}; border:none; border-radius:8px; padding:4px 10px; "
                            f"font-size:11px; font-weight:{'600' if active else '400'}; }}")

    def _load_news(self) -> None:
        self._render_news(logic.get_news(self.cfg))
        self._render_headlines(logic.get_headlines(self.cfg))

    def _render_headlines(self, data: dict[str, Any]) -> None:
        theme = THEMES[self._theme_name()]
        _clear_layout(self.headlines_area)
        items = data.get("items") or []
        if data.get("error") or not items:
            msg = QLabel(data.get("error") or "No headlines yet. They load in the background (or click Refresh).")
            msg.setWordWrap(True)
            msg.setStyleSheet(f"color:{theme['muted']}; font-size:11px; background:transparent;")
            self.headlines_area.addWidget(msg)
        mine = [x for x in items if not x.get("explore")]
        wide = [x for x in items if x.get("explore")]
        for label, group in (("FOR YOUR WORK", mine), ("\U0001f30d THE BIG PICTURE", wide)):
            if not group:
                continue
            head = QLabel(label)
            head.setStyleSheet(f"color:{theme['text']}; font-size:10px; font-weight:700; letter-spacing:0.5px; "
                               "margin-top:6px; background:transparent;")
            self.headlines_area.addWidget(head)
            for item in group:
                self.headlines_area.addWidget(HeadlineRow(item, theme, self._opener("headline", item)))

    def _maybe_refresh_news(self) -> None:
        if logic.news_refresh_due(self.cfg):
            self._refresh_news(force=False)

    def _refresh_news(self, force: bool) -> None:
        if self._news_running:
            return
        self._news_running = True
        self.refresh_news_btn.setEnabled(False)
        self.news_updated_label.setText("updating\u2026")
        self._run_async(lambda: logic.refresh_news_and_headlines(self.cfg, force=force), self._on_news_ready)

    def _on_news_ready(self, data: Any) -> None:
        self._news_running = False
        self.refresh_news_btn.setEnabled(True)
        data = data if isinstance(data, dict) else {}
        self._render_news(data.get("news") or {})
        self._render_headlines(data.get("headlines") or {})

    def _render_news(self, data: dict[str, Any]) -> None:
        theme = THEMES[self._theme_name()]
        _clear_layout(self.news_area)
        items = data.get("items") or []
        if data.get("error") or not items:
            msg = QLabel(data.get("error") or "No news yet. It loads in the background (or click Refresh).")
            msg.setWordWrap(True)
            msg.setStyleSheet(f"color:{theme['muted']}; font-size:11px; background:transparent;")
            self.news_area.addWidget(msg)
        for item in items:
            self.news_area.addWidget(NewsCard(item, theme, self._opener("news", item)))
        updated = data.get("updated_at")
        if not self._news_running:
            self.news_updated_label.setText("updated " + _time_ago(updated) if updated else "")
        for lbl in (self.news_hint, self.news_updated_label):
            lbl.setStyleSheet(f"color:{theme['muted']}; font-size:10.5px; background:transparent;")

    def _load_market(self) -> None:
        self._render_market(logic.get_market(self.cfg))

    def _maybe_refresh_market(self) -> None:
        if logic.market_refresh_due(self.cfg):
            self._refresh_market(force=False)
        if logic.trends_due(self.cfg):
            self._refresh_research(force=False)

    # ------------------------------------------------------------------ research trends
    def _load_research(self) -> None:
        self._render_research(logic.get_trends(self.cfg))

    def _refresh_research(self, force: bool) -> None:
        if getattr(self, "_research_running", False):
            return
        self._research_running = True
        self.refresh_research_btn.setEnabled(False)
        self.research_updated_label.setText("updating\u2026 (about a minute)")
        self._run_async(lambda: logic.refresh_trends(self.cfg, force=force), self._on_research_ready)

    def _on_research_ready(self, data: Any) -> None:
        self._research_running = False
        self.refresh_research_btn.setEnabled(True)
        self._render_research(data if isinstance(data, dict) else {})

    def _render_research(self, data: dict[str, Any]) -> None:
        theme = THEMES[self._theme_name()]
        _clear_layout(self.research_area)
        topics = ", ".join(t["name"] for t in (data.get("topics") or [])[:4])
        self.research_hint.setText(
            "What's moving in research in your field, from OpenAlex: papers gaining citations fastest, new tools "
            "with their code on GitHub, and who leads them. Click a paper for its repo and the people on it."
            + (f"\nYour topics: {topics}." if topics else ""))

        def header(text: str) -> None:
            lbl = QLabel(text)
            lbl.setStyleSheet("font-size:10.5px; font-weight:700; letter-spacing:0.5px; margin-top:6px; "
                              f"color:{theme['text']}; background:transparent;")
            self.research_area.addWidget(lbl)

        if data.get("error") or not (data.get("rising") or data.get("tools")):
            msg = QLabel(data.get("error") or "No research trends yet. They load in the background "
                                              "(or click Refresh).")
            msg.setWordWrap(True)
            msg.setStyleSheet(f"color:{theme['muted']}; font-size:11px; background:transparent;")
            self.research_area.addWidget(msg)
        if data.get("rising"):
            header("\U0001f525 RISING IN YOUR FIELD")
            for p in data["rising"]:
                self.research_area.addWidget(self._research_card(p, theme, "rising"))
        if data.get("tools"):
            header("\U0001f6e0\ufe0f TOOLS WITH PAPERS")
            for p in data["tools"]:
                self.research_area.addWidget(self._research_card(p, theme, "tool"))
        if data.get("people"):
            header("\U0001f469\u200d\U0001f52c PEOPLE BEHIND THE TRENDS")
            for person in data["people"]:
                self.research_area.addWidget(ResearcherRow(person, theme, logic.open_link))
        updated = data.get("updated_at")
        if not getattr(self, "_research_running", False):
            self.research_updated_label.setText("updated " + _time_ago(updated) if updated else "")
        for lbl in (self.research_hint, self.research_updated_label):
            lbl.setStyleSheet(f"color:{theme['muted']}; font-size:10.5px; background:transparent;")

    def _research_card(self, paper: dict[str, Any], theme: dict[str, Any], kind: str) -> "ResearchCard":
        repo_item = {"full_name": (paper.get("repos") or [""])[0], "description": paper.get("title", "")}
        return ResearchCard(paper, theme, self._opener("news", paper), self._opener("repo", repo_item),
                            self._on_research_people, self.avatar_loader, kind=kind)

    def _on_research_people(self, card: "ResearchCard", repo: str) -> None:
        self._run_async(lambda: logic.repo_people(self.cfg, repo),
                        lambda people: card.set_people(people if isinstance(people, list) else [],
                                                       self._opener("person", {"username": repo})))

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
        mentions = logic.news_mentions([r.get("repo", "") for r in rows])
        for row in rows:
            row = {**row, "news": mentions.get(row.get("repo", ""))}
            self.market_area.addWidget(MarketRow(row, theme, self._opener("repo", row), self.avatar_loader))
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
            hint = QLabel("No launches yet. They load with the next board refresh (or click Refresh).")
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
        self._render_brain()
        self.chart.set_history(history)
        if latest.get("timestamp"):
            self.model_footer_label.setText(
                f"Last retrained {_time_ago(latest['timestamp'])}. Follow people you like, then run "
                f"mygeeky learn -- every follow-back you get teaches it more. Hover the chart for details.")
        else:
            self.model_footer_label.setText("No retrains yet -- run mygeeky bootstrap, then mygeeky learn.")

    def _render_brain(self) -> None:
        brain = logic.get_brain(self.cfg)
        theme = THEMES[self._theme_name()]
        self.interest_map.set_data(brain["user"], brain["field"], brain["learned"], brain["explore"])
        self.brain_intro.setText("Four models shape what you see: your research field, what you've been into "
                                 "lately, room to explore, and who's likely to follow you back.")
        dot = lambda c: f"<span style='color:{c}; font-size:13px'>\u25cf</span>"  # noqa: E731
        ring = f"<span style='color:{MAP_EXPLORE}; font-size:13px'>\u25cc</span>"
        self.map_legend.setText(
            f"{dot(MAP_FIELD)} your research field &nbsp; {dot(MAP_LEARNED)} what you're into lately "
            f"(bigger = stronger) &nbsp; {ring} new territory today. Hover a point for more."
            + ("" if brain["learned"] else "<br><i>Nothing learned yet: click people, repos and news, "
                                           "or follow, star and fork on GitHub, and your map grows.</i>"))
        for key, tile in self.teach_tiles.items():
            tile.set_value(brain["taught"][key])
        self.teach_hint.setText(
            (f"Each action fades to half after {brain['half_life']:g} days, so your map follows where your "
             "work is going. Forks count most, then follows and stars, then clicks.")
            if brain["learning"] else "Learning is off (mygeeky config set interest_learning true).")
        self.explore_donut.set_share(brain["explore_share"])
        share = round(brain["explore_share"] * 100)
        self.explore_label.setText(
            (f"{share}% of every list (People, Repos, News, Research) is kept for things outside your usual "
             "interests, marked 🔭." + (f" Today: {', '.join(brain['explore'])}." if brain["explore"] else ""))
            if share else "Exploration is off (mygeeky config set explore_share 0.2 turns it on).")
        self.brain_title.setStyleSheet(f"color:{theme['text']}; font-size:15px; font-weight:700; background:transparent;")
        for lbl in (self.brain_intro, self.map_legend, self.teach_hint, self.explore_label):
            lbl.setStyleSheet(f"color:{theme['muted']}; font-size:10.5px; background:transparent;")
        for lbl in (self.map_header, self.teach_header, self.explore_header, self.followback_header):
            lbl.setStyleSheet(f"color:{theme['text']}; font-size:10.5px; font-weight:700; letter-spacing:0.5px; "
                              "margin-top:8px; background:transparent;")
        self.interest_map.set_theme_colors(theme["text"])
        self.explore_donut.set_theme_colors(theme["text"])
        for tile in self.teach_tiles.values():
            tile.apply_theme(theme)
        self._render_keywords()

    # ------------------------------------------------------------------ your keywords
    KW_HINT = ("<span style='color:#34d399'>● green</span>: myGeeKy knows what it means and also looks "
               "for what goes with it. <span style='color:#f87171'>● red</span>: used as a plain word "
               "for now, and passed on so the next dictionary learns it. Click a keyword to see more.")

    def _render_keywords(self) -> None:
        theme = THEMES[self._theme_name()]
        data = logic.get_keywords(self.cfg)
        self._kw_rows = data["rows"]
        self.kw_completer.setModel(QStringListModel(data["vocabulary"], self.kw_completer))
        if not self._kw_rows:
            chips = f"<span style='color:{theme['muted']}'>No keywords yet. Add a few: they shape every list.</span>"
        else:
            parts = []
            for i, row in enumerate(self._kw_rows):
                color = "#34d399" if row["known"] else "#f87171"
                parts.append(f"<a href='kw:{i}' style='color:{color}; text-decoration:none'>● "
                             f"{html.escape(row['word']).replace(' ', '&nbsp;')}</a>&nbsp;<a href='rm:{i}' style='color:{theme['muted']}; "
                             f"text-decoration:none'>✕</a>")
            chips = " &nbsp;&nbsp; ".join(parts)
        self.kw_chips.setText(f"<span style='font-size:12px'>{chips}</span>")
        self.kw_detail.setText(self.KW_HINT)
        self.kw_detail.setTextFormat(Qt.RichText)
        self.kw_header.setStyleSheet(f"color:{theme['text']}; font-size:10.5px; font-weight:700; "
                                     "letter-spacing:0.5px; margin-top:8px; background:transparent;")
        self.kw_detail.setStyleSheet(f"color:{theme['muted']}; font-size:10.5px; background:transparent;")
        self.kw_input.setStyleSheet(f"QLineEdit {{ background:{theme['card_bg']}; color:{theme['text']}; "
                                    f"border:1px solid {theme['btn_bg']}; border-radius:7px; padding:4px 6px; }}")
        self.kw_add.setStyleSheet(f"QPushButton {{ background:{theme['section_btn']}; color:{theme['text']}; "
                                  "border:none; border-radius:7px; padding:5px 10px; }")

    def _keyword_at(self, link: str) -> tuple[str, dict[str, Any]] | None:
        try:
            action, idx = link.split(":", 1)
            return action, self._kw_rows[int(idx)]
        except (ValueError, IndexError, AttributeError):
            return None

    def _on_keyword_hover(self, link: str) -> None:
        hit = self._keyword_at(link) if link else None
        if hit is None or hit[0] != "kw":
            self.kw_detail.setText(self.KW_HINT)
            return
        self.kw_detail.setText(self._keyword_explained(hit[1]))

    def _keyword_explained(self, row: dict[str, Any]) -> str:
        word = html.escape(row["word"])
        if row["known"]:
            related = ", ".join(html.escape(r) for r in row["related"]) or "its own topic"
            return f"<b>{word}</b> also brings in: {related}."
        return (f"<b>{word}</b> isn't in the dictionary yet, so it's matched as a plain word. "
                "Click it to suggest it to myGeeKy's maker (a GitHub issue you submit).")

    def _on_keyword_link(self, link: str) -> None:
        hit = self._keyword_at(link)
        if hit is None:
            return
        action, row = hit
        if action == "rm":
            words = [r["word"] for r in self._kw_rows if r is not row]
            self._save_keywords(words)
        elif row["known"]:
            self.kw_detail.setText(self._keyword_explained(row))
        else:
            logic.suggest_keyword(row["word"])
            self.kw_detail.setText(f"Your browser opened a suggestion for <b>{html.escape(row['word'])}</b>: "
                                   "click <b>Submit new issue</b> there to send it. Thank you!")

    def _on_add_keyword(self) -> None:
        word = " ".join(self.kw_input.text().split())
        if not word:
            return
        self.kw_input.clear()
        self._save_keywords([r["word"] for r in getattr(self, "_kw_rows", [])] + [word])

    def _save_keywords(self, words: list[str]) -> None:
        self.kw_add.setEnabled(False)

        def done(result: Any) -> None:
            self.kw_add.setEnabled(True)
            self._render_keywords()
            if isinstance(result, dict) and result.get("note"):
                self.kw_detail.setText(html.escape(result["note"]))
        self._run_async(lambda: logic.set_keywords(self.cfg, words), done)

    def _style_model_grade(self) -> None:
        color = _auc_color(getattr(self, "_model_auc", None)).name()
        self.model_grade_label.setStyleSheet(
            f"color:{color}; font-size:20px; font-weight:700; background:transparent;")

    def _play_model_animations(self) -> None:
        for widget in (self.auc_gauge, self.weight_bars, self.chart, *self.model_tiles.values(),
                       self.interest_map, self.explore_donut, *self.teach_tiles.values()):
            widget.play()

    # ------------------------------------------------------------------ tabs
    def _switch_tab(self, name: str) -> None:
        self.active_tab = name
        self.content_stack.setCurrentIndex(self._tab_order.index(name))
        self._update_tab_styles()
        if name == "badges":
            self._render_badges()
            logic.mark_badges_seen(self.cfg, [f"{b['id']}:{b['tier']}" for b in self._badges.get("earned", [])])
            self._update_badge_tab_label()
        if name == "model":  # re-read (it's a local file) and replay the entrance
            self._load_model_history()
            self._play_model_animations()
