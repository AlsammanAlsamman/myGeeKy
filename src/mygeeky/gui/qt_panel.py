"""The Qt widget tree for the live glass panel. Kept separate from app.py
so app.py (and its business-logic functions) can be imported/tested without
requiring PySide6 to be importable."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QPointF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPen, QPixmap
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
from ..config import MyGeekyConfig

ASSETS_DIR = Path(__file__).parent / "assets"
ICON_WINDOW = ASSETS_DIR / "icon_64.png"
ICON_HEADER = ASSETS_DIR / "icon_32.png"

SWATCH_GRADIENTS = {
    "frosted": "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #fff6ee, stop:1 #cfe0ff)",
    "midnight": "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #2a2a3d, stop:1 #0c0c14)",
    "aurora": "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #ff6fd8, stop:0.5 #7a5cff, stop:1 #35e0c1)",
}

AVATAR_PALETTE = ["#e08a4f", "#7aa6e0", "#5ac8a8", "#ff6fd8", "#7a5cff", "#35c2e0", "#e05c5c"]


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
                 on_open: Callable[[str], bool]) -> None:
        super().__init__()
        self.setObjectName("card")
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 8, 8, 8)
        row.setSpacing(8)
        row.addWidget(_avatar_label(item.get("username", "?")))

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
    def __init__(self, event: dict[str, Any], theme: dict[str, Any], on_open: Callable[[str], bool]) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 6, 0, 6)
        row.setSpacing(8)
        row.addWidget(_avatar_label(event.get("actor", "?"), size=24))

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


class MyGeekyPanel(QWidget):
    def __init__(self, cfg: MyGeekyConfig) -> None:
        super().__init__()
        self.cfg = cfg
        self.active_tab = "suggestions"
        self._workers: list[_Worker] = []

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
        self._load_suggestions()
        self._refresh_activity(force=False)
        self._load_model_history()

        self._activity_timer = QTimer(self)
        self._activity_timer.timeout.connect(lambda: self._refresh_activity(force=False))
        self._activity_timer.start(60_000)

    # ------------------------------------------------------------------ UI construction
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        outer.addWidget(self.stack)

        self.folded_widget = QPushButton("myGeeKy")
        self.folded_widget.setCursor(Qt.PointingHandCursor)
        self.folded_widget.clicked.connect(self.unfold)
        self.stack.addWidget(self.folded_widget)

        self.panel_frame = QFrame()
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
        for name, label in (("suggestions", "Suggestions"), ("activity", "Activity"), ("model", "Model")):
            btn = QPushButton(label)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, n=name: self._switch_tab(n))
            self.tab_buttons[name] = btn
            tabs_row.addWidget(btn)
        panel_layout.addLayout(tabs_row)

        self.content_stack = QStackedWidget()
        panel_layout.addWidget(self.content_stack, 1)

        self.content_stack.addWidget(self._build_suggestions_tab())
        self.content_stack.addWidget(self._build_activity_tab())
        self.content_stack.addWidget(self._build_model_tab())

        self.stack.addWidget(self.panel_frame)
        self.stack.setCurrentWidget(self.panel_frame)

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
        radius = 20
        if self.cfg.gui_dock_side == "left":
            corner = f"0px {radius}px {radius}px 0px"
        else:
            corner = f"{radius}px 0px 0px {radius}px"

        self.panel_frame.setStyleSheet(
            f"#panel {{ background:{theme['bg']}; border:1px solid {theme['border']}; "
            f"border-radius:{corner}; }}"
            f"QLabel {{ color:{theme['text']}; }}"
        )
        self.folded_widget.setStyleSheet(
            f"QPushButton {{ background:{theme['bg']}; border:1px solid {theme['border']}; "
            f"border-radius:{corner}; color:{theme['text']}; font-weight:600; }}"
        )
        self.status_label.setStyleSheet(f"font-size:11px; color:{theme['muted']}; background:transparent;")
        self.activity_updated_label.setStyleSheet(f"color:{theme['muted']}; font-size:11px; background:transparent;")

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

    def _set_card_list(self, layout, items: list[dict[str, Any]], score_key: str, theme: dict[str, Any]) -> None:
        _clear_layout(layout)
        if not items:
            empty = QLabel("Nothing here yet — try Refresh.")
            empty.setStyleSheet(f"color:{theme['muted']}; font-size:11px; background:transparent;")
            layout.addWidget(empty)
            return
        for item in items:
            layout.addWidget(SuggestionCard(item, score_key, theme, logic.open_profile))

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
                self.activity_area.addWidget(ActivityItem(event, theme, logic.open_profile))
        fetched_at = (data or {}).get("fetched_at")
        if fetched_at:
            self.activity_updated_label.setText("updated " + _time_ago(fetched_at))

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
        index = {"suggestions": 0, "activity": 1, "model": 2}[name]
        self.content_stack.setCurrentIndex(index)
        self._update_tab_styles()
