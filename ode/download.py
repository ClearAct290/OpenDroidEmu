"""Download + install worker and the progress dialog shared by core / system image downloads."""
from __future__ import annotations

import re
import time
from collections import deque

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
                             QPushButton, QVBoxLayout)

from . import paths, sdk, system
from .util import fmt_eta, fmt_mb, fmt_speed

DL_SHARE = 0.85          # share of a job's progress bar used by the download (rest = extraction)


class DownloadWorker(QThread):
    # fraction 0..1, status text, speed (B/s), eta (s or -1), downloaded bytes, total bytes
    progress = pyqtSignal(float, str, float, float, float, float)
    succeeded = pyqtSignal()
    failed = pyqtSignal(str)
    aborted = pyqtSignal()

    def __init__(self, jobs: list):
        super().__init__()
        self.jobs = jobs
        self._cancel = False
        self._samples: deque = deque()
        self._last_emit = 0.0

    def cancel(self):
        self._cancel = True

    def is_cancelled(self) -> bool:
        return self._cancel

    # ----------------------------------------------------------------- helpers
    def _speed(self, done: float) -> float:
        now = time.time()
        self._samples.append((now, done))
        while self._samples and now - self._samples[0][0] > 4.0:
            self._samples.popleft()
        if len(self._samples) < 2:
            return 0.0
        (t0, b0), (t1, b1) = self._samples[0], self._samples[-1]
        return (b1 - b0) / (t1 - t0) if t1 > t0 else 0.0

    def run(self):
        total = float(sum(j.size for j in self.jobs)) or 1.0
        try:
            need_mb = total / 1048576.0 * 3.2
            if system.free_mb(paths.CORE_DIR) < need_mb:
                raise RuntimeError(f"Not enough free disk space for the download and installation. "
                                   f"About {need_mb:,.0f} MB are needed on the drive that holds the core folder.")
            paths.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
            paths.EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
            finished_weight = 0.0
            done_bytes = 0.0
            for idx, job in enumerate(self.jobs):
                weight = (job.size or 1) / total
                zip_path = paths.DOWNLOAD_DIR / f"{idx}_{re.sub(r'[^A-Za-z0-9._-]+', '_', job.name)}.zip"
                self._samples.clear()

                def on_bytes(n, job=job, weight=weight, base=finished_weight):
                    nonlocal done_bytes
                    done_bytes += n
                    now = time.time()
                    if now - self._last_emit < 0.1:
                        return
                    self._last_emit = now
                    speed = self._speed(done_bytes)
                    eta = (total - done_bytes) / speed if speed > 1 else -1
                    in_job = min(1.0, max(0.0, (done_bytes - (done_before[0])) / (job.size or 1)))
                    frac = base + weight * DL_SHARE * in_job
                    self.progress.emit(min(frac, 0.999), f"Downloading {job.name}...", speed, eta,
                                       done_bytes, total)

                done_before = [done_bytes]
                try:
                    sdk.download(job, zip_path, on_bytes, self.is_cancelled)
                    self.progress.emit(finished_weight + weight * DL_SHARE, f"Verifying {job.name}...",
                                       0.0, -1, done_bytes, total)

                    def on_extract(f, job=job, weight=weight, base=finished_weight):
                        self.progress.emit(min(base + weight * (DL_SHARE + (1 - DL_SHARE) * f), 0.999),
                                           f"Extracting {job.name}... {int(f * 100)}%", 0.0, -1,
                                           done_bytes, total)

                    sdk.install_zip(job, zip_path, on_extract, self.is_cancelled)
                finally:
                    try:
                        zip_path.unlink()
                    except OSError:
                        pass
                finished_weight += weight
            self.progress.emit(1.0, "Done", 0.0, 0, total, total)
            self.succeeded.emit()
        except sdk.Cancelled:
            self.aborted.emit()
        except Exception as exc:                       # noqa: BLE001
            self.failed.emit(str(exc) or exc.__class__.__name__)


class DownloadDialog(QDialog):
    """Modal progress window. exec_() returns Accepted only when everything installed."""

    def __init__(self, parent, title: str, jobs: list):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(470)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.error = ""
        self._finished = False
        total = sum(j.size for j in jobs)

        self.head = QLabel(f"<b>{title}</b>")
        self.status = QLabel("Starting...")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.l_bytes = QLabel(f"0 MB / {fmt_mb(total)}")
        self.l_speed = QLabel("Speed: -")
        self.l_eta = QLabel("ETA: -")
        for lab in (self.l_bytes, self.l_speed, self.l_eta):
            lab.setObjectName("muted")
        stats = QHBoxLayout()
        stats.addWidget(self.l_bytes)
        stats.addStretch(1)
        stats.addWidget(self.l_speed)
        stats.addSpacing(14)
        stats.addWidget(self.l_eta)
        self.btn = QPushButton("Cancel")
        self.btn.clicked.connect(self._on_button)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(8)
        lay.addWidget(self.head)
        lay.addWidget(self.status)
        lay.addWidget(self.bar)
        lay.addLayout(stats)
        lay.addSpacing(6)
        lay.addLayout(row)

        self.worker = DownloadWorker(jobs)
        self.worker.progress.connect(self._on_progress)
        self.worker.succeeded.connect(self._on_ok)
        self.worker.failed.connect(self._on_fail)
        self.worker.aborted.connect(self._on_abort)

    def showEvent(self, e):
        super().showEvent(e)
        if not self.worker.isRunning() and not self._finished:
            self.worker.start()

    def _on_progress(self, frac, text, speed, eta, done, total):
        self.bar.setValue(int(frac * 1000))
        self.status.setText(text)
        self.l_bytes.setText(f"{fmt_mb(done)} / {fmt_mb(total)}")
        self.l_speed.setText(f"Speed: {fmt_speed(speed)}")
        self.l_eta.setText(f"ETA: {fmt_eta(eta) if eta >= 0 else '-'}")

    def _on_ok(self):
        self._finished = True
        self.worker.wait()
        self.accept()

    def _on_fail(self, msg: str):
        self._finished = True
        self.error = msg
        self.worker.wait()
        self.reject()

    def _on_abort(self):
        self._finished = True
        self.worker.wait()
        QDialog.reject(self)

    def _on_button(self):
        self.btn.setEnabled(False)
        self.btn.setText("Cancelling...")
        self.status.setText("Cancelling...")
        self.worker.cancel()

    def reject(self):                                   # Esc / window close = cancel
        if self.worker.isRunning():
            self._on_button()
            return
        super().reject()

    def done(self, r):
        if self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(5000)
        super().done(r)


def run_download(parent, title: str, jobs: list, success_text: str = "") -> bool:
    """Show the progress dialog for `jobs`. True when all installed; shows errors itself.
    success_text: if given, a 'Success' message box is shown afterwards."""
    dlg = DownloadDialog(parent, title, jobs)
    ok = dlg.exec_() == QDialog.Accepted
    if ok and success_text:
        QMessageBox.information(parent, "Success", success_text)
    elif not ok and dlg.error:
        QMessageBox.critical(parent, "Download failed", dlg.error)
    return ok
