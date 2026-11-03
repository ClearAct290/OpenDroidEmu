"""Floating control sidebar (volume, Home, Back, Tasks, Power, shared-folder sync, force close)."""
from __future__ import annotations

import ctypes

from PyQt5.QtCore import QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PyQt5.QtWidgets import (QAbstractButton, QFrame, QLabel, QMenu, QMessageBox, QVBoxLayout,
                             QWidget)

from . import system, theme

IS_WIN = system.IS_WIN

# (kind, tooltip, needs a booted Android)
BUTTONS = [
    ("vol_up", "Volume up", True),
    ("vol_down", "Volume down", True),
    ("home", "Home", True),
    ("back", "Back", True),
    ("tasks", "Tasks (recent apps)", True),
    ("power", "Power button", True),
    ("sync", "Shared folder", False),
    ("kill", "Force close - kills the emulator", False),
]


# ---------------------------------------------------------------- icon drawing
def draw_icon(p: QPainter, kind: str, r: QRectF, color: QColor) -> None:
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(color, max(1.8, r.width() / 11.0), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    cx, cy, w = r.center().x(), r.center().y(), r.width()
    u = w / 20.0

    def pt(x, y):
        return QPointF(cx + x * u, cy + y * u)

    if kind in ("vol_up", "vol_down"):
        spk = QPolygonF([pt(-8, -3), pt(-4, -3), pt(0, -7), pt(0, 7), pt(-4, 3), pt(-8, 3)])
        p.setBrush(color)
        p.drawPolygon(spk)
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(pt(-3, -4), pt(5, 4)), -45 * 16, 90 * 16)
        if kind == "vol_up":
            p.drawArc(QRectF(pt(-4, -8), pt(9, 8)), -45 * 16, 90 * 16)
    elif kind == "home":
        roof = QPolygonF([pt(-8, 0), pt(0, -8), pt(8, 0)])
        p.drawPolyline(roof)
        body = QPainterPath()
        body.moveTo(pt(-5, -3))
        body.lineTo(pt(-5, 7))
        body.lineTo(pt(5, 7))
        body.lineTo(pt(5, -3))
        p.drawPath(body)
    elif kind == "back":
        p.drawPolygon(QPolygonF([pt(6, -7), pt(-6, 0), pt(6, 7)]))
    elif kind == "tasks":
        p.drawRoundedRect(QRectF(pt(-6, -6), pt(6, 6)), 2 * u, 2 * u)
    elif kind == "power":
        p.drawArc(QRectF(pt(-7, -6), pt(7, 8)), 120 * 16, -300 * 16)
        p.drawLine(pt(0, -9), pt(0, 0))
    elif kind == "sync":
        p.drawArc(QRectF(pt(-7, -7), pt(7, 7)), 30 * 16, 150 * 16)
        p.drawArc(QRectF(pt(-7, -7), pt(7, 7)), 210 * 16, 150 * 16)
        p.setBrush(color)
        p.drawPolygon(QPolygonF([pt(6, -6), pt(7.5, 0), pt(2, -1.5)]))
        p.drawPolygon(QPolygonF([pt(-6, 6), pt(-7.5, 0), pt(-2, 1.5)]))
    elif kind == "kill":
        p.drawEllipse(QRectF(pt(-8, -8), pt(8, 8)))
        p.drawLine(pt(-3.5, -3.5), pt(3.5, 3.5))
        p.drawLine(pt(-3.5, 3.5), pt(3.5, -3.5))
    p.restore()


class IconButton(QAbstractButton):
    def __init__(self, kind: str, tip: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setToolTip(tip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(44, 44)
        self._hover = False

    def sizeHint(self):
        return QSize(44, 44)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        enabled = self.isEnabled()
        if enabled and (self._hover or self.isDown()):
            bg = theme.col("accent") if self.kind != "kill" else theme.col("danger")
            bg.setAlpha(255 if self.isDown() else 70)
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(2, 2, -2, -2), 10, 10)
        if not enabled:
            color = theme.col("disabled")
        elif self.kind == "kill":
            color = theme.col("danger")
        else:
            color = theme.col("text")
        draw_icon(p, self.kind, QRectF(self.rect()).adjusted(9, 9, -9, -9), color)


class SidebarPanel(QFrame):
    """The button column. demo=True is the non-functional preview used by the guide."""
    action = pyqtSignal(str)
    drag_started = pyqtSignal()

    def __init__(self, demo: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.demo = demo
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 8)
        lay.setSpacing(2)
        self.grip = QLabel("ODE")
        self.grip.setAlignment(Qt.AlignCenter)
        self.grip.setObjectName("muted")
        self.grip.setToolTip("Drag to move the sidebar")
        self.grip.setCursor(Qt.SizeAllCursor)
        lay.addWidget(self.grip)
        self.buttons: dict = {}
        for kind, tip, _needs in BUTTONS:
            if kind == "kill":
                lay.addSpacing(6)
            b = IconButton(kind, tip)
            b.clicked.connect(lambda _=False, k=kind: self._clicked(k))
            lay.addWidget(b, 0, Qt.AlignHCenter)
            self.buttons[kind] = b
        self.setFixedWidth(62)

    def _clicked(self, kind: str):
        if not self.demo:
            self.action.emit(kind)

    def configure(self, recovery: bool, has_shared: bool) -> None:
        for kind, _tip, needs_android in BUTTONS:
            b = self.buttons[kind]
            if kind == "sync":
                b.setEnabled(has_shared)
                b.setToolTip("Shared folder: send to / get from the device" if has_shared
                             else "No shared folder was set for this instance")
            elif needs_android:
                b.setEnabled(not recovery)
        if recovery:
            self.grip.setText("REC")


# ---------------------------------------------------------------- Windows helpers
if IS_WIN:
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, wintypes.UINT]
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    HWND_TOPMOST = wintypes.HWND(-1)
    SWP_NOSIZE, SWP_NOACTIVATE = 0x0001, 0x0010


def _virtual_screen():
    """(left, top, right, bottom) of the whole desktop in physical pixels."""
    if IS_WIN:
        gm = ctypes.windll.user32.GetSystemMetrics
        x, y, w, h = gm(76), gm(77), gm(78), gm(79)
        return x, y, x + w, y + h
    return 0, 0, 100000, 100000


def _cursor_pos():
    if IS_WIN:
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y
    return None


class FloatingSidebar(QWidget):
    """Frameless always-on-top window that follows the emulator window."""

    GAP = 6

    def __init__(self, session, parent=None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle("ODE Sidebar")
        self.session = session
        self.panel = SidebarPanel(False, self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.panel)
        self.panel.configure(session.current == "recovery", bool(session.inst.shared_dir))
        self.panel.action.connect(self._action)
        self.panel.grip.installEventFilter(self)
        session.message.connect(self._on_message)
        session.state.connect(self._on_state)
        self._offset = None            # (dx, dy) from the emulator window's top-left, physical px
        self._drag = None
        self._hidden_by_min = False
        self.adjustSize()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._follow)
        self.timer.start(250)
        self._placed = False

    # ----------------------------------------------------------------- actions
    def _action(self, kind: str):
        s = self.session
        if kind == "kill":
            r = QMessageBox.question(self, "Force close",
                                     f"Force close \"{s.inst.title}\"?\nThe emulator is killed immediately and "
                                     "anything unsaved inside Android is lost.",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r == QMessageBox.Yes:
                s.kill()
        elif kind == "sync":
            menu = QMenu(self)
            menu.addAction("Send shared folder to device", s.push_shared)
            menu.addAction("Get files from device", s.pull_shared)
            menu.addSeparator()
            hint = menu.addAction("Device folder: /sdcard/ODE_Shared")
            hint.setEnabled(False)
            menu.exec_(self.panel.buttons["sync"].mapToGlobal(self.panel.buttons["sync"].rect().bottomLeft()))
        else:
            s.press(kind)

    def _on_message(self, ok: bool, text: str):
        box = QMessageBox.information if ok else QMessageBox.warning
        box(self, "Shared folder", text)

    def _on_state(self, st: str):
        if st in ("booted", "recovery"):
            self.panel.configure(st == "recovery", bool(self.session.inst.shared_dir))

    # ----------------------------------------------------------------- following / dragging
    def eventFilter(self, obj, ev):
        if obj is self.panel.grip:
            if ev.type() == ev.MouseButtonPress and ev.button() == Qt.LeftButton:
                self._drag = True
                self._drag_origin = (_cursor_pos(), self._pos_physical(), ev.globalPos(), self.pos())
                return True
            if ev.type() == ev.MouseMove and self._drag:
                self._do_drag(ev)
                return True
            if ev.type() == ev.MouseButtonRelease:
                self._drag = None
                return True
        return super().eventFilter(obj, ev)

    def _pos_physical(self):
        if IS_WIN:
            r = wintypes.RECT()
            _user32.GetWindowRect(int(self.winId()), ctypes.byref(r))
            return r.left, r.top
        return self.x(), self.y()

    def _do_drag(self, ev):
        cur0, pos0, g0, qpos0 = self._drag_origin
        if IS_WIN and cur0:
            cx, cy = _cursor_pos()
            x, y = pos0[0] + cx - cur0[0], pos0[1] + cy - cur0[1]
            self._move_physical(x, y)
            rect = system.find_window_rect(self.session.window_title_part)
            if rect:
                self._offset = (x - rect[0], y - rect[1])
        else:
            d = ev.globalPos() - g0
            self.move(qpos0 + d)

    def _move_physical(self, x: int, y: int):
        if IS_WIN:
            _user32.SetWindowPos(int(self.winId()), HWND_TOPMOST, int(x), int(y), 0, 0,
                                 SWP_NOSIZE | SWP_NOACTIVATE)
        else:
            self.move(int(x), int(y))

    def _size_physical(self):
        dpr = self.devicePixelRatioF() if IS_WIN else 1.0
        return int(self.width() * dpr), int(self.height() * dpr)

    def _follow(self):
        if self._drag:
            return
        rect = system.find_window_rect(self.session.window_title_part)
        if rect is None:
            if not IS_WIN and not self._placed:        # no window lookup off Windows: park top-right
                scr = self.screen().availableGeometry() if self.screen() else None
                if scr:
                    self.move(scr.right() - self.width() - 20, scr.top() + 80)
                self._placed = True
            return
        if rect[0] < -30000:                           # emulator minimised -> hide the sidebar too
            if self.isVisible():
                self.hide()
                self._hidden_by_min = True
            return
        if self._hidden_by_min or not self.isVisible():
            self.show()
            self._hidden_by_min = False
        w, h = self._size_physical()
        vl, vt, vr, vb = _virtual_screen()
        if self._offset is not None:
            x, y = rect[0] + self._offset[0], rect[1] + self._offset[1]
        else:
            x = rect[2] + self.GAP
            if x + w > vr:                              # no room on the right -> dock on the left
                x = rect[0] - w - self.GAP
            if x < vl:                                  # no room either side -> inside the window
                x = max(vl, rect[2] - w - 12)
            y = rect[1] + 40
        x = min(max(x, vl), vr - w)
        y = min(max(y, vt), vb - h)
        self._move_physical(x, y)
        self._placed = True
