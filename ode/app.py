"""Program entry point."""
from __future__ import annotations

import ctypes
import sys
import threading
import time
import traceback

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QMessageBox

from . import APP_NAME, paths, theme
from .settings import Settings
from .util import app_icon

ERROR_LOG = paths.DATA_DIR / "ode_error.log"


def _log(text: str) -> None:
    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')}\n{text}\n")
    except OSError:
        pass


def _install_excepthooks() -> None:
    """Without a console (and with PyQt5 aborting on unhandled slot errors) a crash would be silent:
    log it to data/ode_error.log and tell the user instead."""
    busy = {"on": False}

    def hook(etype, value, tb):
        text = "".join(traceback.format_exception(etype, value, tb))
        _log(text)
        if sys.__stderr__ is not None:
            sys.__stderr__.write(text)
        if QApplication.instance() is not None and not busy["on"]:
            busy["on"] = True
            try:
                QMessageBox.critical(None, APP_NAME,
                                     f"ODE ran into an unexpected error:\n\n{value}\n\n"
                                     f"Details were saved to:\n{ERROR_LOG}")
            finally:
                busy["on"] = False

    sys.excepthook = hook
    threading.excepthook = lambda a: _log("".join(traceback.format_exception(a.exc_type, a.exc_value,
                                                                              a.exc_traceback)))


def main() -> int:
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    try:                                                    # 125% / 150% Windows scaling stays exact
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except AttributeError:                                  # Qt < 5.14
        pass
    if sys.platform.startswith("win"):                      # own taskbar identity + icon
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OpenDroidEmu.ODE.1")
        except Exception:                                   # noqa: BLE001
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(app_icon())
    _install_excepthooks()
    settings = Settings()
    theme.setup_app_font(app)
    theme.apply_theme(app, settings.get("theme", "light"))

    from .main_window import MainWindow                      # after the theme so widgets start styled
    win = MainWindow(settings)
    win.show()
    win.start()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
