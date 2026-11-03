"""Small shared helpers: background tasks, number formatting (always MB), asset loading."""
from __future__ import annotations

import threading

from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtGui import QGuiApplication, QIcon, QPixmap

from . import paths


# ------------------------------------------------------------------ formatting
def fmt_mb(n_bytes: float) -> str:
    """Bytes -> '1,234.5 MB' (all sizes in ODE are shown in MB)."""
    return f"{max(0.0, n_bytes) / 1048576.0:,.1f} MB"


def fmt_speed(bytes_per_s: float) -> str:
    if bytes_per_s <= 0:
        return "-"
    mb = bytes_per_s / 1048576.0
    return f"{mb:.1f} MB/s" if mb >= 10 else f"{mb:.2f} MB/s"


def fmt_eta(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    if s >= 3600:
        return f"{s // 3600}h {s % 3600 // 60:02d}m"
    if s >= 60:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s}s"


# ---------------------------------------------------------------- assets / icon
def app_icon() -> QIcon:
    icon = QIcon(paths.asset("icon.ico"))
    if icon.isNull():
        icon = QIcon(paths.asset("icon.png"))
    return icon


def asset_pixmap(name: str, size: int) -> QPixmap:
    """assets/<name> scaled to fit size x size (logical px, keeps the aspect ratio, HiDPI aware).
    Note: pm.size() is in device pixels - use pm.size() / pm.devicePixelRatioF() for logical size."""
    pm = QPixmap(paths.asset(name))
    if pm.isNull():
        return QPixmap()
    screen = QGuiApplication.primaryScreen()
    dpr = max(1.0, screen.devicePixelRatio() if screen else 1.0)
    out = pm.scaled(int(size * dpr), int(size * dpr), Qt.KeepAspectRatio, Qt.SmoothTransformation)
    out.setDevicePixelRatio(dpr)
    return out


# ------------------------------------------------------------------ background tasks
class _Bridge(QObject):
    """Lives in the GUI thread; worker threads emit into it so callbacks run on the GUI thread."""
    finished = pyqtSignal(object, object, object)       # callback, result, error

    def __init__(self):
        super().__init__()
        self.finished.connect(self._deliver, Qt.QueuedConnection)

    def _deliver(self, callback, result, error):
        try:
            callback(result, error)
        except RuntimeError as exc:
            if "deleted" not in str(exc):                # widget closed while the task ran: ignore
                raise


_bridge = None


def run_task(fn, callback) -> None:
    """Run fn() in a worker thread; then callback(result, error) on the GUI thread
    (error is the exception or None). Must be first called from the GUI thread."""
    global _bridge
    if _bridge is None:
        _bridge = _Bridge()
    bridge = _bridge

    def work():
        try:
            res, err = fn(), None
        except Exception as exc:                          # noqa: BLE001
            res, err = None, exc
        bridge.finished.emit(callback, res, err)

    threading.Thread(target=work, daemon=True).start()
