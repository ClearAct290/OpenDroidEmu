"""Quick Setup guide: dimmed overlay, highlight cutout, arrow, Bugdroid and a step card."""
from __future__ import annotations

import math
from dataclasses import dataclass

from PyQt5.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PyQt5.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                             QToolButton, QVBoxLayout, QWidget)

from . import theme
from .util import asset_pixmap


@dataclass
class Step:
    title: str
    text: str
    target: str = ""            # name understood by MainWindow.guide_target()
    page: str = "manager"       # "manager" | "create"
    demo_card: bool = False     # show the example instance card
    show_core: bool = False     # force-show the Download/Update Core button
    bug: int = 84               # Bugdroid size in px


STEPS = [
    Step("Welcome!",
         "Hi, I'm Bugdroid! I'll guide you through the features and UI of ODE!\n\n"
         "ODE (OpenDroidEmu) is a small, ad-free program that downloads, configures and launches Google's "
         "stock Android Emulator for you - for gaming, app testing or everyday use.", bug=132),
    Step("Download / Update Core",
         "The emulator core is Google's official Android Emulator. This button says Download Core while it "
         "isn't installed and turns into Update Core when Google releases a newer version. The core is "
         "installed into the core folder next to ODE.", "core", show_core=True),
    Step("Guide", "This button opens this Quick Setup guide again whenever you want it.", "guide"),
    Step("Light / Dark", "Switch between the light and the dark theme here. You can also do it from this "
         "guide.", "theme"),
    Step("About", "Version info, license notes and the disclaimer: ODE is not related to the OpenDroid "
         "Custom ROM project. When a new ODE version is out on GitHub, ODE tells you at startup.", "about"),
    Step("Instance manager",
         "All your Android devices (\"instances\") are listed here. The card you see is only an example - "
         "it isn't a real instance.", "list", demo_card=True),
    Step("Star", "Star an instance to keep it at the top of the list. Starred instances stay first; "
         "newer instances are placed right below them.", "card_star", demo_card=True),
    Step("Settings", "Change an instance after it was created: its title, display, graphics API, CPU cores, "
         "RAM, max FPS, V-Sync, boot mode (Quick Boot or Cold Boot) and SD card size. Only the architecture, the Android "
         "version and the disk space are fixed. Close the instance first.", "card_edit", demo_card=True),
    Step("Dev Control", "Available while Android is running: a window of ADB tools for that instance - install "
         "apps by dropping .apk files on it (or on the card), browse and copy files, take screenshots, record the "
         "screen, read logs, forward ports and more.", "card_dev", demo_card=True),
    Step("Delete", "Deletes the instance and all of its files, after asking you to confirm. Starred or not - "
         "it can't be undone.", "card_delete", demo_card=True),
    Step("Launch",
         "Left click starts Android. The first time, ODE asks to download the system files it needs. "
         "Right click starts the instance in Android Recovery mode instead. Right click the card for more, "
         "like Force close if an instance ever hangs.", "card_launch", demo_card=True),
    Step("Create instance", "Press this to make a new instance. Let's look at the creation page.",
         "create_button"),
    Step("Title and Android version",
         "New instances are titled \"My Android Instance #1\", \"#2\" and so on - change it if you like. "
         "Choose x86, x86_64, x86 / x86_64 + ARM apps (slower, but runs ARM-only apps) or "
         "Standalone ARM (for ARM64 PCs). Then pick the Android version - from the oldest available to the "
         "newest.", "grp_basic", page="create"),
    Step("Graphics API", "Choose DirectX, OpenGL or Vulkan. APIs your PC can't use are marked as not "
         "supported on your system.", "grp_gfx", page="create"),
    Step("Storage",
         "Choose where the instance files go. The disk limit is the size of Android's internal storage - "
         "pick pre-allocated or dynamically growing. The SD card is a separate virtual card (for photos and downloads); "
         "its file takes its full size on your drive right away.",
         "grp_storage", page="create"),
    Step("Performance",
         "Pick CPU cores (up to your CPU's threads minus 2), RAM (up to half of your RAM), a max FPS from "
         "30 to 240 and optionally V-Sync. Boot mode: Quick Boot (the default) resumes the state Android saved "
         "when you closed the emulator window, so it starts in seconds - the very first start, and any start "
         "after a Force close, is still a full boot. Cold Boot starts Android from scratch every time. You can "
         "switch between them later with Settings.", "grp_perf", page="create"),
    Step("Create", "Press Create and the instance appears in the manager. Architecture, Android version and "
         "disk space can't be changed later - everything else can, with Settings. The SD card size can be changed too, but that replaces the card with an empty one.", "create_buttons",
         page="create"),
    Step("You're all set!", "You can reopen this guide with the Guide button at the top at any time. "
         "Have fun!", bug=132),
]


def _clamp(v, lo, hi):
    return max(lo, min(v, hi)) if lo <= hi else lo


class GuideOverlay(QWidget):
    closed = pyqtSignal(bool)           # True = don't show the guide at startup again

    CARD_W = 400
    GAP = 100                           # room between target and card for arrow + Bugdroid
    M = 14

    def __init__(self, win, dont_show: bool = False):
        super().__init__(win)
        self.win = win
        self.i = 0
        self._hole = None
        self._arrow = None
        self.setFocusPolicy(Qt.StrongFocus)

        self.card = QFrame(self)
        self.card.setObjectName("guideCard")
        self.card.setFixedWidth(self.CARD_W)
        self.lb_title = QLabel()
        self.lb_title.setObjectName("cardTitle")
        self.lb_text = QLabel()
        self.lb_text.setWordWrap(True)
        self.lb_text.setTextFormat(Qt.PlainText)
        self.lb_count = QLabel()
        self.lb_count.setObjectName("muted")
        self.chk = QCheckBox("Don't show me again")
        self.chk.setChecked(dont_show)
        self.btn_theme = QToolButton()
        self.btn_theme.clicked.connect(self._toggle_theme)
        self.btn_skip = QPushButton("Skip")
        self.btn_back = QPushButton("Back")
        self.btn_next = QPushButton("Next")
        self.btn_next.setObjectName("primary")
        self.btn_skip.clicked.connect(lambda: self.finish())
        self.btn_back.clicked.connect(self.back)
        self.btn_next.clicked.connect(self.next)

        r1 = QHBoxLayout()
        r1.addWidget(self.chk)
        r1.addStretch(1)
        r1.addWidget(self.btn_theme)
        r2 = QHBoxLayout()
        r2.addWidget(self.lb_count)
        r2.addStretch(1)
        r2.addWidget(self.btn_skip)
        r2.addWidget(self.btn_back)
        r2.addWidget(self.btn_next)
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.setSpacing(8)
        lay.addWidget(self.lb_title)
        lay.addWidget(self.lb_text)
        lay.addSpacing(4)
        lay.addLayout(r1)
        lay.addLayout(r2)

        self.bug = QLabel(self)
        self.bug.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._bug_cache: dict = {}

        win.installEventFilter(self)
        self.setGeometry(win.rect())
        self.raise_()
        self.show()
        self.setFocus()
        self._go(0)

    # ------------------------------------------------------------------ navigation
    def _go(self, i: int):
        self.i = i
        step = STEPS[i]
        self.win.guide_enter(step)
        self.lb_title.setText(step.title)
        self.lb_text.setText(step.text)
        self.lb_count.setText(f"{i + 1} / {len(STEPS)}")
        last = i == len(STEPS) - 1
        self.btn_next.setText("Finish" if last else "Next")
        self.btn_back.setEnabled(i > 0)
        self.btn_skip.setVisible(not last)
        self._update_theme_button()
        pm = self._bug_cache.get(step.bug)
        if pm is None:
            pm = self._bug_cache[step.bug] = asset_pixmap("guide_bugdroid.png", step.bug)
        self.bug.setPixmap(pm)
        self.bug.resize(pm.size() / pm.devicePixelRatioF())     # logical size (pm.size() is in device px)
        self._relayout()
        QTimer.singleShot(60, self._relayout)           # after the page switch has been laid out
        QTimer.singleShot(400, self._relayout)          # ... and after async content (version list) arrived

    def next(self):
        if self.i >= len(STEPS) - 1:
            self.finish()
        else:
            self._go(self.i + 1)

    def back(self):
        if self.i > 0:
            self._go(self.i - 1)

    def finish(self):
        self.win.removeEventFilter(self)
        self.win.guide_exit()
        dont = self.chk.isChecked()
        self.hide()
        self.deleteLater()
        self.closed.emit(dont)

    def _toggle_theme(self):
        self.win.toggle_theme()
        self._update_theme_button()
        QTimer.singleShot(0, self._relayout)

    def _update_theme_button(self):
        self.btn_theme.setText("\u2600  Light mode" if theme.current() == "dark" else "\u263E  Dark mode")

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key_Escape:
            self.finish()
        elif k in (Qt.Key_Right, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.next()
        elif k in (Qt.Key_Left, Qt.Key_Backspace):
            self.back()
        else:
            super().keyPressEvent(e)

    def eventFilter(self, obj, ev):
        if obj is self.win and ev.type() == QEvent.Resize:
            self.setGeometry(self.win.rect())
            self._relayout()
        return False

    # ------------------------------------------------------------------ geometry
    def _target_rect(self, step: Step):
        if not step.target:
            return None
        w = self.win.guide_target(step.target)
        if w is None or not w.isVisible():
            return None
        p = w.parentWidget()
        while p is not None and p is not self.win:      # scroll it into view first
            if isinstance(p, QScrollArea):
                p.ensureWidgetVisible(w, 20, 20)
                break
            p = p.parentWidget()
        r = QRect(w.mapTo(self.win, QPoint(0, 0)), w.size())
        p = w.parentWidget()
        while p is not None and p is not self.win:      # clip to scroll viewports
            if isinstance(p, QScrollArea):
                vp = p.viewport()
                r = r.intersected(QRect(vp.mapTo(self.win, QPoint(0, 0)), vp.size()))
            p = p.parentWidget()
        return r if r.isValid() and not r.isEmpty() else None

    def _relayout(self):
        if not self.isVisible():
            return
        step = STEPS[self.i]
        W, H, M = self.width(), self.height(), self.M
        cw = self.CARD_W
        self.card.layout().activate()
        ch = max(self.card.layout().totalHeightForWidth(cw), self.card.sizeHint().height())
        self.card.resize(cw, ch)
        bw, bh = self.bug.width(), self.bug.height()
        r = self._target_rect(step)
        self._hole = None
        self._arrow = None

        if r is None:                                   # greeting / farewell: centred card, big Bugdroid
            cx, cy = (W - cw) // 2 + bw // 3, (H - ch) // 2
            self.card.move(cx, cy)
            self.bug.move(max(M, cx - bw + 6), cy + ch - bh + 12)
            self.update()
            return

        hole = r.adjusted(-6, -6, 6, 6)
        self._hole = hole
        G = self.GAP
        slack = {"below": H - hole.bottom() - G - ch - M, "above": hole.top() - G - ch - M,
                 "right": W - hole.right() - G - cw - M, "left": hole.left() - G - cw - M}
        side = next((s for s in ("below", "above", "right", "left") if slack[s] >= 0), None)
        fits = side is not None
        if side is None:
            side = max(slack, key=slack.get)

        if side in ("below", "above"):
            x = int(_clamp(hole.center().x() - cw // 2, M, W - cw - M))
            y = hole.bottom() + G if side == "below" else hole.top() - G - ch
            y = int(_clamp(y, M, H - ch - M))
            ax = _clamp(hole.center().x(), max(x + 30, hole.left() + 10), min(x + cw - 30, hole.right() - 10))
            if side == "below":
                p0, p1 = QPointF(ax, y), QPointF(ax, hole.bottom() + 4)
                by = hole.bottom() + (G - bh) / 2
            else:
                p0, p1 = QPointF(ax, y + ch), QPointF(ax, hole.top() - 4)
                by = hole.top() - G + (G - bh) / 2
            bx = ax + 16
            if bx + bw > W - M:
                bx = ax - 16 - bw
        else:
            y = int(_clamp(hole.center().y() - ch // 2, M, H - ch - M))
            x = hole.right() + G if side == "right" else hole.left() - G - cw
            x = int(_clamp(x, M, W - cw - M))
            ay = _clamp(hole.center().y(), max(y + 30, hole.top() + 10), min(y + ch - 30, hole.bottom() - 10))
            if side == "right":
                p0, p1 = QPointF(x, ay), QPointF(hole.right() + 4, ay)
                bx = hole.right() + (G - bw) / 2
            else:
                p0, p1 = QPointF(x + cw, ay), QPointF(hole.left() - 4, ay)
                bx = hole.left() - G + (G - bw) / 2
            by = ay + 14
            if by + bh > H - M:
                by = ay - 14 - bh

        if not fits and hole.width() >= cw + 2 * M and hole.height() >= ch + bh + 90:
            # target fills the page (the instance list): put the card inside it, at the bottom, with the
            # arrow pointing up at the list content
            x = int(_clamp(hole.center().x() - cw // 2, M, W - cw - M))
            y = int(_clamp(hole.bottom() - ch - 16, M, H - ch - M))
            self.card.move(x, y)
            ax = x + cw // 2
            self._arrow = (QPointF(ax, y), QPointF(ax, y - bh))
            self.bug.move(int(ax + 18), int(y - bh + 4))
            self.bug.raise_()
            self.update()
            return

        self.card.move(x, y)
        card_rect = QRect(x, y, cw, ch)
        if fits or not card_rect.intersects(hole):
            self._arrow = (p0, p1)
            self.bug.move(int(bx), int(by))
        else:
            # target too big for a clear side: card overlaps it; Bugdroid hugs the card, arrow points at the
            # nearest inner edge of the highlighted area
            self.bug.move(int(_clamp(x - bw + 24, M, W - bw - M)), int(_clamp(y - bh // 2, M, H - bh - M)))
            cp = card_rect.center()
            tip = QPointF(_clamp(cp.x(), hole.left() + 8, hole.right() - 8),
                          _clamp(cp.y(), hole.top() + 8, hole.bottom() - 8))
            start = QPointF(_clamp(tip.x(), x + 20, x + cw - 20), y if tip.y() < cp.y() else y + ch)
            if card_rect.contains(tip.toPoint()):
                self._arrow = None
            else:
                self._arrow = (start, tip)
        self.bug.raise_()
        self.update()

    # ------------------------------------------------------------------ painting
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        dim = QColor(theme.hexcol("overlay"))
        dim.setAlpha(170)
        path = QPainterPath()
        path.addRect(QRectF(self.rect()))
        accent = theme.col("accent")
        if self._hole is not None:
            hole = QPainterPath()
            hole.addRoundedRect(QRectF(self._hole), 8, 8)
            path = path.subtracted(hole)
        p.fillPath(path, dim)
        if self._hole is not None:
            p.setPen(QPen(accent, 3))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(self._hole), 8, 8)
        if self._arrow:
            a, b = self._arrow
            pen = QPen(accent, 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            p.setPen(pen)
            ang = math.atan2(b.y() - a.y(), b.x() - a.x())
            head = 16
            base = QPointF(b.x() - head * 0.8 * math.cos(ang), b.y() - head * 0.8 * math.sin(ang))
            p.drawLine(a, base)
            left = QPointF(b.x() - head * math.cos(ang - 0.45), b.y() - head * math.sin(ang - 0.45))
            right = QPointF(b.x() - head * math.cos(ang + 0.45), b.y() - head * math.sin(ang + 0.45))
            p.setBrush(accent)
            p.setPen(Qt.NoPen)
            p.drawPolygon(QPolygonF([b, left, right]))
