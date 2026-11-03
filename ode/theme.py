"""Light / dark theme: Qt's Fusion style + a matching palette + one stylesheet.

Everything colour-related lives in PALETTES, so the look can be changed in one place.
col()/hexcol() give other modules (sidebar, guide overlay, instance cards) the same colours.
"""
from __future__ import annotations

import re
import sys

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QImage, QPainter, QPalette, QPen, QPolygonF

from . import paths

PALETTES = {
    "light": {
        "bg": "#f1f3f5", "panel": "#ffffff", "panel2": "#e9ecef", "input": "#ffffff",
        "border": "#ccd1d8", "hover": "#e3e7eb",
        "text": "#1e2328", "muted": "#667085", "disabled": "#a3a9b3",
        "accent": "#1f9d57", "accent_hover": "#188a4a", "accent_text": "#ffffff",
        "select_text": "#ffffff",
        "danger": "#d13438", "warn": "#a85f00", "overlay": "#0e1217",
    },
    "dark": {
        "bg": "#1d2024", "panel": "#272b31", "panel2": "#30353c", "input": "#1a1d21",
        "border": "#444b55", "hover": "#383e46",
        "text": "#e8eaed", "muted": "#9aa3ae", "disabled": "#69717b",
        "accent": "#3ddc84", "accent_hover": "#5ee69a", "accent_text": "#06210f",
        "select_text": "#06210f",
        "danger": "#ff6b6b", "warn": "#f0b24a", "overlay": "#000000",
    },
}

_current = "light"


def current() -> str:
    return _current


def col(name: str) -> QColor:
    """A fresh QColor of the current theme (callers may modify it, e.g. setAlpha)."""
    return QColor(PALETTES[_current][name])


def hexcol(name: str) -> str:
    return PALETTES[_current][name]


# ------------------------------------------------------------------------ palette
def _palette(c: dict) -> QPalette:
    g = lambda k: QColor(c[k])                       # noqa: E731
    p = QPalette()
    p.setColor(QPalette.Window, g("bg"))
    p.setColor(QPalette.WindowText, g("text"))
    p.setColor(QPalette.Base, g("input"))
    p.setColor(QPalette.AlternateBase, g("panel2"))
    p.setColor(QPalette.ToolTipBase, g("panel2"))
    p.setColor(QPalette.ToolTipText, g("text"))
    p.setColor(QPalette.Text, g("text"))
    p.setColor(QPalette.Button, g("panel"))
    p.setColor(QPalette.ButtonText, g("text"))
    p.setColor(QPalette.BrightText, QColor("#ffffff"))
    p.setColor(QPalette.Link, g("accent"))
    p.setColor(QPalette.LinkVisited, g("accent"))
    p.setColor(QPalette.Highlight, g("accent"))
    p.setColor(QPalette.HighlightedText, g("select_text"))
    p.setColor(QPalette.PlaceholderText, g("muted"))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, g("disabled"))
    p.setColor(QPalette.Disabled, QPalette.Highlight, g("border"))
    p.setColor(QPalette.Disabled, QPalette.HighlightedText, g("disabled"))
    return p


# ---------------------------------------------------------------------- stylesheet
# @name@ is replaced by the colour of that name. Spin boxes are left to the
# Fusion style + palette on purpose (styling them by stylesheet breaks their arrows).
QSS = """
QToolTip { color: @text@; background-color: @panel2@; border: 1px solid @border@; padding: 4px 6px; }

QFrame#topbar { background: @panel@; border: none; border-bottom: 1px solid @border@; }
QFrame#footer { background: @panel@; border: none; border-top: 1px solid @border@; }
QFrame#banner { background: @panel2@; border: 1px solid @border@; border-radius: 8px; }
QFrame#card { background: @panel@; border: 1px solid @border@; border-radius: 10px; }
QFrame#card[demo="true"] { border: 1px dashed @accent@; }
QFrame#guideCard { background: @panel@; border: 2px solid @accent@; border-radius: 12px; }
QFrame#sidebar { background: @panel@; border: 1px solid @border@; border-radius: 14px; }

QLabel#appTitle { font-size: 15pt; font-weight: 600; }
QLabel#pageTitle { font-size: 17pt; font-weight: 600; }
QLabel#cardTitle { font-size: 12pt; font-weight: 600; }
QLabel#muted { color: @muted@; }
QLabel#danger { color: @danger@; }
QLabel#warn { color: @warn@; }

QPushButton { background: @panel@; color: @text@; border: 1px solid @border@; border-radius: 6px;
              padding: 5px 14px; min-height: 18px; }
QPushButton:hover { background: @hover@; border-color: @muted@; }
QPushButton:pressed { background: @panel2@; }
QPushButton:disabled { color: @disabled@; background: @panel2@; border-color: @border@; }
QPushButton#primary { background: @accent@; color: @accent_text@; border: 1px solid @accent@;
                      font-weight: 600; }
QPushButton#primary:hover { background: @accent_hover@; border-color: @accent_hover@; }
QPushButton#primary:pressed { background: @accent@; }
QPushButton#primary:disabled { background: @panel2@; color: @disabled@; border: 1px solid @border@; }

QToolButton { background: transparent; color: @text@; border: none; border-radius: 6px; padding: 4px 8px; }
QToolButton:hover { background: @hover@; }

QLineEdit { background: @input@; color: @text@; border: 1px solid @border@; border-radius: 6px;
            padding: 4px 8px; selection-background-color: @accent@; selection-color: @select_text@; }
QLineEdit:focus { border: 1px solid @accent@; }
QLineEdit:disabled { color: @disabled@; background: @panel2@; }
QPlainTextEdit { background: @input@; color: @text@; border: 1px solid @border@; border-radius: 6px;
                 padding: 6px; selection-background-color: @accent@; selection-color: @select_text@; }

QComboBox { background: @input@; color: @text@; border: 1px solid @border@; border-radius: 6px;
            padding: 4px 8px; min-height: 20px; }
QComboBox:hover { border-color: @muted@; }
QComboBox:focus { border-color: @accent@; }
QComboBox:disabled { color: @disabled@; background: @panel2@; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right; width: 24px; border: none; }
QComboBox::down-arrow { image: url("@arrow@"); width: 10px; height: 10px; }
QComboBox::down-arrow:disabled { image: url("@arrow_off@"); }
QComboBox QAbstractItemView { background: @panel@; color: @text@; border: 1px solid @border@; outline: 0;
                              selection-background-color: @accent@; selection-color: @select_text@; }
QComboBox QAbstractItemView::item:disabled { color: @disabled@; }

QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; }
QCheckBox::indicator:unchecked { image: url("@cb_off@"); }
QCheckBox::indicator:checked { image: url("@cb_on@"); }
QCheckBox::indicator:unchecked:disabled { image: url("@cb_off_dis@"); }
QCheckBox::indicator:checked:disabled { image: url("@cb_on_dis@"); }

QGroupBox { background: transparent; border: 1px solid @border@; border-radius: 8px;
            margin-top: 14px; padding: 14px 10px 8px 10px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 12px; padding: 0 6px; }
QGroupBox QLabel, QGroupBox QCheckBox { font-weight: normal; }

QProgressBar { background: @panel2@; color: @text@; border: 1px solid @border@; border-radius: 6px;
               text-align: center; min-height: 12px; }
QProgressBar::chunk { background: @accent@; border-radius: 5px; }

QMenu { background: @panel@; color: @text@; border: 1px solid @border@; padding: 4px; }
QMenu::item { padding: 6px 22px; border-radius: 4px; }
QMenu::item:selected { background: @accent@; color: @select_text@; }
QMenu::item:disabled { color: @disabled@; background: transparent; }
QMenu::separator { height: 1px; background: @border@; margin: 4px 8px; }

QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar::handle:vertical { background: @border@; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: @muted@; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
QScrollBar::handle:horizontal { background: @border@; border-radius: 4px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background: @muted@; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
"""


def _png(name: str, draw) -> str:
    """Render a 32x32 icon into data/cache (stylesheets can only use image files); returns its path."""
    f = paths.CACHE_DIR / f"{name}.png"
    img = QImage(32, 32, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    draw(p)
    p.end()
    img.save(str(f))
    return f.as_posix()


def _images(name: str, c: dict) -> dict:
    def pen(color, w):
        return QPen(QColor(color), w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)

    def chevron(color):
        def draw(p):
            p.setPen(pen(color, 4))
            p.drawPolyline(QPolygonF([QPointF(8, 12), QPointF(16, 20), QPointF(24, 12)]))
        return draw

    def box(checked, disabled):
        def draw(p):
            box_rect = QRectF(3, 3, 26, 26)
            if checked:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(c["border"] if disabled else c["accent"]))
                p.drawRoundedRect(box_rect, 6, 6)
                p.setBrush(Qt.NoBrush)
                p.setPen(pen(c["disabled"] if disabled else c["accent_text"], 4))
                p.drawPolyline(QPolygonF([QPointF(9, 16.5), QPointF(14, 21.5), QPointF(23, 10.5)]))
            else:
                p.setPen(pen(c["border"] if disabled else c["muted"], 2.5))
                p.setBrush(QColor(c["panel2"] if disabled else c["input"]))
                p.drawRoundedRect(box_rect, 6, 6)
        return draw

    return {
        "arrow": _png(f"arrow_{name}_on", chevron(c["muted"])),
        "arrow_off": _png(f"arrow_{name}_off", chevron(c["disabled"])),
        "cb_off": _png(f"cb_{name}_off", box(False, False)),
        "cb_on": _png(f"cb_{name}_on", box(True, False)),
        "cb_off_dis": _png(f"cb_{name}_off_dis", box(False, True)),
        "cb_on_dis": _png(f"cb_{name}_on_dis", box(True, True)),
    }


def build_qss(name: str) -> str:
    c = dict(PALETTES[name])
    c.update(_images(name, PALETTES[name]))
    return re.sub(r"@(\w+)@", lambda m: c[m.group(1)], QSS)


# ---------------------------------------------------------------------- public API
def setup_app_font(app) -> None:
    if sys.platform.startswith("win"):
        app.setFont(QFont("Segoe UI", 9))
    else:
        f = app.font()
        if f.pointSizeF() < 9.5:
            f.setPointSizeF(10)
        app.setFont(f)


def apply_theme(app, name: str) -> None:
    global _current
    _current = name if name in PALETTES else "light"
    if app.style().objectName().lower() != "fusion":
        app.setStyle("Fusion")
    app.setPalette(_palette(PALETTES[_current]))
    app.setStyleSheet(build_qss(_current))
