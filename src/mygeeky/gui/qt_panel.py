"""The Qt widget tree for the live glass panel. Kept separate from app.py
so app.py (and its business-logic functions) can be imported/tested without
requiring PySide6 to be importable."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPointF,
    Qt,
    QPropertyAnimation,
    QRectF,
    QThread,
    QTimer,
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
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
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

SWATCH_GRADIENTS = {
    "frosted": "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #fff6ee, stop:1 #cfe0ff)",
    "midnight": "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #2a2a3d, stop:1 #0c0c14)",
    "aurora": "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #ff6fd8, stop:0.5 #7a5cff, stop:1 #35e0c1)",
}

AVATAR_PALETTE = ["#e08a4f", "#7aa6e0", "#5ac8a8", "#ff6fd8", "#7a5cff", "#35c2e0", "#e05c5c"]


def _build_spotlight_items(activity_events: list[dict[str, Any]],
                            suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
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

    interleaved: list[dict[str, Any]] = []
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


class TrendChart(QWidget):
    """Hand-drawn AUC-over-time line chart -- no charting dependency needed."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(120)
        self._points: list[float] = []
        self._text_color = QColor("#f0f0f5")
        self._accent_color = QColor("#7fd8ff")

    def set_theme_colors(self, text_color: str, accent_color: str) -> None:
        self._text_color = QColor(text_color)
        self._accent_color = QColor(accent_color)
        self.update()

    def set_history(self, history: list[dict[str, Any]]) -> None:
        self._points = [h["auc"] for h in history if h.get("auc") is not None]
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt's own naming convention
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        grid_color = QColor(self._text_color)
        grid_color.setAlpha(30)
        painter.setPen(QPen(grid_color, 1))
        for i in range(5):
            y = h / 4 * i
            painter.drawLine(0, int(y), w, int(y))

        if len(self._points) < 2:
            muted = QColor(self._text_color)
            muted.setAlpha(140)
            painter.setPen(QPen(muted))
            painter.drawText(10, h // 2, "Not enough retrains yet to chart a trend")
            painter.end()
            return

        pad = 10
        n = len(self._points)
        xs = [pad + (i / (n - 1)) * (w - 2 * pad) for i in range(n)]
        ys = [h - pad - max(0.0, min(1.0, p)) * (h - 2 * pad) for p in self._points]

        painter.setPen(QPen(self._accent_color, 2))
        for i in range(n - 1):
            painter.drawLine(int(xs[i]), int(ys[i]), int(xs[i + 1]), int(ys[i + 1]))

        painter.setBrush(self._accent_color)
        painter.setPen(Qt.NoPen)
        for x, y in zip(xs, ys):
            painter.drawEllipse(QPointF(x, y), 3, 3)
        painter.end()


class SuggestionCard(QFrame):
    def __init__(self, item: dict[str, Any], score_key: str, theme: dict[str, Any],
                 on_open: Callable[[str], bool], loader: "AvatarLoader | None" = None) -> None:
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
        bio_label.setStyleSheet(f"color:{theme['muted']}; font-size:11px; background:transparent;")
        body.addWidget(bio_label)
        row.addLayout(body, 1)

        open_btn = QPushButton("Open →")
        open_btn.setCursor(Qt.PointingHandCursor)
        open_btn.setStyleSheet(
            f"QPushButton {{ background:{theme['btn_bg']}; color:{theme['text']}; border:none; "
            f"border-radius:7px; padding:5px 8px; font-size:11px; }}"
            f"QPushButton:hover {{ background:{theme['btn_hover']}; }}"
        )
        url = item.get("profile_url", "")
        open_btn.clicked.connect(lambda: on_open(url))
        row.addWidget(open_btn)

        self.setStyleSheet(f"#card {{ background:{theme['card_bg']}; border-radius:10px; }}")


class ActivityItem(QFrame):
    def __init__(self, event: dict[str, Any], theme: dict[str, Any], on_open: Callable[[str], bool],
                 loader: "AvatarLoader | None" = None) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 6, 0, 6)
        row.setSpacing(8)
        row.addWidget(_avatar_widget(event.get("actor", "?"), event.get("actor_avatar", ""), 24, loader))

        body = QVBoxLayout()
        body.setSpacing(2)
        actor = event.get("actor", "")
        verb = event.get("verb", "")
        repo = event.get("repo", "")
        text = f"{actor} {verb}" + (f" in {repo}" if repo else "")
        text_label = QLabel(text)
        text_label.setWordWrap(True)
        text_label.setStyleSheet(f"color:{theme['text']}; font-size:11.5px; background:transparent;")
        body.addWidget(text_label)
        time_label = QLabel(_time_ago(event.get("created_at", "")))
        time_label.setStyleSheet(f"color:{theme['muted']}; font-size:10px; background:transparent;")
        body.addWidget(time_label)
        row.addLayout(body, 1)

        self.setCursor(Qt.PointingHandCursor)
        profile_url = event.get("profile_url", "")
        self.mousePressEvent = lambda ev: on_open(profile_url)  # noqa: ARG005


class SpotlightCard(QFrame):
    """One slide in the Live tab's ticker: a photo + headline + detail,
    normalized from either an activity event or a suggestion (see
    MyGeekyPanel._build_spotlight_items)."""

    KIND_BADGES = {"activity": "LIVE", "suggestion": "SUGGESTED"}

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
    """A single card at a time, auto-advancing through `set_items()` on a
    timer, sliding the new card up from below while the old one slides up
    and out the top -- a vertical news-ticker feed, one story at a time."""

    def __init__(self, on_open: Callable[[str], bool], loader: "AvatarLoader | None") -> None:
        super().__init__()
        self._on_open = on_open
        self._loader = loader
        self._theme: dict[str, Any] = THEMES["midnight"]
        self._items: list[dict[str, Any]] = []
        self._index = -1
        self._current: SpotlightCard | None = None
        self._anim_group: QParallelAnimationGroup | None = None
        self.setFixedHeight(72)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)

    def set_theme(self, theme: dict[str, Any]) -> None:
        self._theme = theme
        if self._items:
            self._show(max(self._index, 0), animate=False)

    def set_items(self, items: list[dict[str, Any]]) -> None:
        self._items = items
        if not items:
            if self._current is not None:
                self._current.deleteLater()
                self._current = None
            self._index = -1
            return
        self._index = 0
        self._show(0, animate=False)

    def start(self, interval_ms: int) -> None:
        if self._items:
            self._timer.start(max(1200, interval_ms))

    def stop(self) -> None:
        self._timer.stop()

    def is_running(self) -> bool:
        return self._timer.isActive()

    def _advance(self) -> None:
        if not self._items:
            return
        self._index = (self._index + 1) % len(self._items)
        self._show(self._index, animate=True)

    def _show(self, index: int, animate: bool) -> None:
        item = self._items[index]
        new_card = SpotlightCard(item, self._theme, self._on_open, self._loader)
        new_card.setParent(self)
        new_card.setGeometry(0, 0, self.width(), self.height())

        old_card = self._current
        self._current = new_card
        new_card.show()

        if not animate or old_card is None:
            new_card.move(0, 0)
            if old_card is not None:
                old_card.deleteLater()
            return

        new_card.move(0, self.height())
        group = QParallelAnimationGroup(self)

        anim_new = QPropertyAnimation(new_card, b"pos", self)
        anim_new.setDuration(420)
        anim_new.setStartValue(QPoint(0, self.height()))
        anim_new.setEndValue(QPoint(0, 0))
        anim_new.setEasingCurve(QEasingCurve.OutCubic)
        group.addAnimation(anim_new)

        anim_old = QPropertyAnimation(old_card, b"pos", self)
        anim_old.setDuration(420)
        anim_old.setStartValue(QPoint(0, 0))
        anim_old.setEndValue(QPoint(0, -self.height()))
        anim_old.setEasingCurve(QEasingCurve.OutCubic)
        group.addAnimation(anim_old)

        group.finished.connect(old_card.deleteLater)
        self._anim_group = group  # keep a reference alive until it finishes
        group.start()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._current is not None:
            self._current.setGeometry(0, 0, self.width(), self.height())


_RGBA_RE = re.compile(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)")
_GRADIENT_STOP_RE = re.compile(r"stop:\s*([\d.]+)\s+((?:rgba?\([^)]*\))|#[0-9a-fA-F]{3,8})")


def _parse_color(spec: str) -> QColor:
    """THEMES colors are Qt-stylesheet strings, e.g. 'rgba(255,255,255,31)'
    (Qt's rgba() alpha is 0-255, not the 0-1 the CSS spec uses elsewhere) --
    QColor's own string constructor doesn't understand rgba(), only
    #rrggbb/#aarrggbb and SVG color names, so it has to be hand-parsed."""
    match = _RGBA_RE.match(spec.strip())
    if match:
        r, g, b = (int(float(match.group(i))) for i in (1, 2, 3))
        a = int(float(match.group(4))) if match.group(4) is not None else 255
        return QColor(r, g, b, a)
    return QColor(spec)


def _parse_bg_brush(spec: str, rect: QRectF) -> QBrush:
    """theme['bg'] is a Qt-stylesheet qlineargradient(...) string (shared with
    the QSS `background:` rule used elsewhere in this file). QColor can't
    read that either -- passing it straight through silently produced solid
    opaque black instead of the intended translucent glass gradient."""
    stops = _GRADIENT_STOP_RE.findall(spec)
    if not stops:
        return QBrush(_parse_color(spec))
    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    for pos, color in stops:
        gradient.setColorAt(float(pos), _parse_color(color))
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
        painter.fillPath(path, _parse_bg_brush(self._bg_spec, rect))
        painter.setPen(QPen(_parse_color(self._border_spec), 1))
        painter.drawPath(path)
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
        # This button doubles as the folded state: a narrow, full-height strip
        # docked to the screen edge, not a compact pill -- so the radius is a
        # small fixed value, never proportional to the (tall) widget height.
        radius = min(self._radius, rect.width() / 2.0, rect.height() / 2.0)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.fillPath(path, _parse_bg_brush(self._bg_spec, rect))
        painter.setPen(QPen(_parse_color(self._border_spec), 1))
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
        self._last_suggestions: list[dict[str, Any]] = []

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
        self._refresh_activity(force=False)
        self._load_model_history()
        self.ticker.start(int(self.cfg.gui_live_rotate_seconds * 1000))

        self._activity_timer = QTimer(self)
        self._activity_timer.timeout.connect(lambda: self._refresh_activity(force=False))
        self._activity_timer.start(60_000)

    # ------------------------------------------------------------------ UI construction
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        outer.addWidget(self.stack)

        self.folded_widget = RoundedButton("myGeeKy")
        self.folded_widget.setCursor(Qt.PointingHandCursor)
        self.folded_widget.clicked.connect(self.unfold)
        self.stack.addWidget(self.folded_widget)

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

        self.swatch_buttons: dict[str, QPushButton] = {}
        for name in ("aurora", "midnight", "frosted"):
            btn = QPushButton()
            btn.setFixedSize(15, 15)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(name.capitalize())
            btn.clicked.connect(lambda checked=False, n=name: self._on_theme_clicked(n))
            self.swatch_buttons[name] = btn
            header.addWidget(btn)

        self.fold_btn = QPushButton("⟩")
        self.fold_btn.setFixedSize(26, 26)
        self.fold_btn.setCursor(Qt.PointingHandCursor)
        self.fold_btn.clicked.connect(self.fold)
        header.addWidget(self.fold_btn)
        panel_layout.addLayout(header)

        self.status_label = QLabel("Loading…")
        self.status_label.setWordWrap(True)
        panel_layout.addWidget(self.status_label)

        tabs_row = QHBoxLayout()
        self.tab_buttons: dict[str, QPushButton] = {}
        for name, label in (("live", "Live"), ("suggestions", "Suggestions"),
                             ("activity", "Activity"), ("model", "Model")):
            btn = QPushButton(label)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, n=name: self._switch_tab(n))
            self.tab_buttons[name] = btn
            tabs_row.addWidget(btn)
        panel_layout.addLayout(tabs_row)

        self.content_stack = QStackedWidget()
        panel_layout.addWidget(self.content_stack, 1)

        self._tab_order = ["live", "suggestions", "activity", "model"]
        self.content_stack.addWidget(self._build_live_tab())
        self.content_stack.addWidget(self._build_suggestions_tab())
        self.content_stack.addWidget(self._build_activity_tab())
        self.content_stack.addWidget(self._build_model_tab())

        self.stack.addWidget(self.panel_frame)
        self.stack.setCurrentWidget(self.panel_frame)

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

        self.ticker = SpotlightTicker(logic.open_profile, self.avatar_loader)
        layout.addWidget(self.ticker)

        hint = QLabel("Recent activity and top suggestions, one at a time — click a card to open the profile.")
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size:10px; background:transparent;")
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _build_suggestions_tab(self) -> QScrollArea:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)

        actions_row = QHBoxLayout()
        hint = QLabel("Click Open to view a profile — you follow manually.")
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
        layout.addWidget(activity_container)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
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

    def _build_model_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        self.model_summary_label = QLabel("Loading…")
        self.model_summary_label.setWordWrap(True)
        layout.addWidget(self.model_summary_label)
        self.chart = TrendChart()
        layout.addWidget(self.chart)
        note = QLabel("AUC trend across retrains (mygeeky bootstrap / mygeeky learn).")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------ theme
    def _theme_name(self) -> str:
        return self.cfg.gui_theme if self.cfg.gui_theme in THEME_NAMES else "midnight"

    def _apply_theme(self) -> None:
        theme = THEMES[self._theme_name()]
        self.panel_frame.set_style(theme["bg"], theme["border"], radius=22.0)
        self.panel_frame.setStyleSheet(f"QLabel {{ color:{theme['text']}; }}")
        self.folded_widget.set_style(theme["bg"], theme["border"], theme["text"])
        folded_font = self.folded_widget.font()
        folded_font.setBold(True)
        self.folded_widget.setFont(folded_font)
        self.status_label.setStyleSheet(f"font-size:11px; color:{theme['muted']}; background:transparent;")
        self.activity_updated_label.setStyleSheet(f"color:{theme['muted']}; font-size:11px; background:transparent;")

        for lbl in (self.stat_friends_label, self.stat_new_label, self.stat_rate_label):
            lbl.setStyleSheet(f"font-size:11px; font-weight:600; color:{theme['text']}; background:transparent;")
        self.ticker.set_theme(theme)

        self.fold_btn.setStyleSheet(
            f"QPushButton {{ background:{theme['btn_bg']}; color:{theme['text']}; border:none; "
            f"border-radius:8px; font-size:14px; }}"
            f"QPushButton:hover {{ background:{theme['btn_hover']}; }}"
        )
        for name, btn in self.swatch_buttons.items():
            active = name == self._theme_name()
            border = f"2px solid {theme['accent']}" if active else f"1px solid {theme['swatch_border']}"
            btn.setStyleSheet(
                f"QPushButton {{ background:{SWATCH_GRADIENTS[name]}; border-radius:7px; border:{border}; }}"
            )
        for btn in (self.refresh_sugg_btn, self.refresh_act_btn):
            btn.setStyleSheet(
                f"QPushButton {{ background:{theme['section_btn']}; color:{theme['text']}; border:none; "
                f"border-radius:8px; padding:6px 10px; font-size:11.5px; }}"
            )
        self.chart.set_theme_colors(theme["text"], theme["accent"])
        self._update_tab_styles()

    def _update_tab_styles(self) -> None:
        theme = THEMES[self._theme_name()]
        for name, btn in self.tab_buttons.items():
            active = name == self.active_tab
            bg = theme["tab_active"] if active else theme["card_bg"]
            btn.setStyleSheet(
                f"QPushButton {{ background:{bg}; color:{theme['text']}; border:none; "
                f"border-radius:8px; padding:6px 0; font-size:11.5px; }}"
            )

    def _on_theme_clicked(self, name: str) -> None:
        if logic.set_theme(self.cfg, name):
            self._apply_theme()
            self._render_suggestions_from_cache()

    def _render_suggestions_from_cache(self) -> None:
        # Re-render already-loaded cards so their theme-dependent styling updates too.
        self._load_suggestions()
        self._refresh_activity(force=False)

    # ------------------------------------------------------------------ fold/unfold/dock
    def _dock(self, folded: bool) -> None:
        screen = self.screen() or QGuiApplication.primaryScreen()
        rect = screen.geometry()
        x, y, w, h = logic._panel_geometry(self.cfg, folded, rect)
        self.setGeometry(x, y, w, h)
        self.stack.setCurrentWidget(self.folded_widget if folded else self.panel_frame)

    def fold(self) -> None:
        self._dock(folded=True)

    def unfold(self) -> None:
        self._dock(folded=False)

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

    def _on_refresh_suggestions(self) -> None:
        theme = THEMES[self._theme_name()]
        _clear_layout(self.followback_area)
        loading = QLabel("Searching GitHub… this can take a minute.")
        loading.setStyleSheet(f"color:{theme['muted']}; font-size:11px; background:transparent;")
        self.followback_area.addWidget(loading)
        self._run_async(lambda: logic.refresh_suggestions(self.cfg), self._on_suggestions_ready)

    def _on_suggestions_ready(self, data: Any) -> None:
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
            layout.addWidget(SuggestionCard(item, score_key, theme, logic.open_profile, self.avatar_loader))

    # ------------------------------------------------------------------ activity
    def _refresh_activity(self, force: bool) -> None:
        self._run_async(lambda: logic.get_activity(self.cfg, force=force), self._on_activity_ready)

    def _on_activity_ready(self, data: Any) -> None:
        theme = THEMES[self._theme_name()]
        events = (data or {}).get("events") or []
        _clear_layout(self.activity_area)
        if not events:
            empty = QLabel("No recent activity from people you follow yet.")
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color:{theme['muted']}; font-size:11px; background:transparent;")
            self.activity_area.addWidget(empty)
        else:
            for event in events:
                self.activity_area.addWidget(ActivityItem(event, theme, logic.open_profile, self.avatar_loader))
        fetched_at = (data or {}).get("fetched_at")
        if fetched_at:
            self.activity_updated_label.setText("updated " + _time_ago(fetched_at))
        self._last_activity_events = events
        self._update_live_ticker()

    # ------------------------------------------------------------------ live spotlight ticker
    def _update_live_ticker(self) -> None:
        items = _build_spotlight_items(self._last_activity_events, self._last_suggestions)
        was_running = self.ticker.is_running()
        self.ticker.set_items(items)
        if was_running:
            self.ticker.start(int(self.cfg.gui_live_rotate_seconds * 1000))

    # ------------------------------------------------------------------ model
    def _load_model_history(self) -> None:
        self._render_model(logic.get_model_history())

    def _render_model(self, history: list[dict[str, Any]]) -> None:
        if not history:
            self.model_summary_label.setText(
                "No model retrains yet — run mygeeky bootstrap or mygeeky learn."
            )
            self.chart.set_history([])
            return
        latest = history[-1]
        prev = history[-2] if len(history) > 1 else None
        trend = ""
        if prev and latest.get("auc") is not None and prev.get("auc") is not None:
            diff = latest["auc"] - prev["auc"]
            trend = " ▲" if diff > 0.001 else " ▼" if diff < -0.001 else " ●"
        auc_text = f"{latest['auc']:.3f}" if latest.get("auc") is not None else "n/a"
        self.model_summary_label.setText(
            f"Training examples: {latest.get('n_train')} ({latest.get('n_pos')} positive)\n"
            f"Cross-validated AUC: {auc_text}{trend}"
        )
        self.chart.set_history(history)

    # ------------------------------------------------------------------ tabs
    def _switch_tab(self, name: str) -> None:
        self.active_tab = name
        self.content_stack.setCurrentIndex(self._tab_order.index(name))
        self._update_tab_styles()
