"""Virtual SD card for an instance: creates / removes the card image the stock emulator uses.

The stock emulator reads <instance>/avd/<id>.avd/sdcard.img when config.ini has hw.sdCard=yes. That file is a raw
FAT32 disk image without a partition table (exactly what Google's own `mksdcard` tool makes). On the first
start the emulator wraps it in a copy-on-write overlay, sdcard.img.qcow2, and from then on only sees the overlay -
so replacing the card (a new size) means removing the image AND the overlay (and the saved Quick Boot snapshots,
which still remember the old card).

ODE creates the image itself before the emulator starts, so it never depends on the emulator creating one.
It uses `mksdcard` from the emulator package when that file exists and a built-in pure Python FAT32 writer
otherwise (the built-in writer needs nothing extra and works on every platform).
"""
from __future__ import annotations

import os
import shutil
import stat
import struct
import time
from pathlib import Path

from . import system

MIN_SD_MB = 64                    # FAT32 needs roughly 33 MB at 512 byte clusters; 64 MB keeps it comfortably valid
MAX_SD_MB = 102400                # 100 GB
DEFAULT_SD_MB = 2048
SECTOR = 512
MB = 1024 * 1024

IMAGE = "sdcard.img"
OVERLAY = "sdcard.img.qcow2"
LABEL = "SDCARD"


def label_for(size_mb: int) -> str:
    if size_mb <= 0:
        return "No SD card"
    return f"{size_mb} MB" if size_mb < 1024 else f"{size_mb / 1024:g} GB"


def valid_size(size_mb: int) -> bool:
    return size_mb == 0 or MIN_SD_MB <= size_mb <= MAX_SD_MB


# --------------------------------------------------------------------------- pure Python FAT32 writer
def _sectors_per_cluster(total_sectors: int) -> int:
    """Microsoft's FAT32 table (512 byte sectors)."""
    mb = total_sectors * SECTOR / MB
    if mb <= 260:
        return 1
    if mb <= 8192:
        return 8
    if mb <= 16384:
        return 16
    if mb <= 32768:
        return 32
    return 64


def fat32_layout(total_sectors: int) -> dict:
    """Geometry of a FAT32 volume with `total_sectors` 512 byte sectors (no partition table)."""
    reserved = 32
    spc = _sectors_per_cluster(total_sectors)
    while True:
        fat = max(1, (total_sectors // spc) * 4 // SECTOR)
        while True:                                   # smallest FAT that covers every cluster it has to map
            data = total_sectors - reserved - 2 * fat
            clusters = data // spc
            need = -(-(clusters + 2) * 4 // SECTOR)
            if need <= fat:
                break
            fat = need
        if clusters >= 65525 or spc == 1:             # below 65525 clusters the volume would be FAT16
            break
        spc //= 2
    return {"reserved": reserved, "spc": spc, "fat_sectors": fat, "clusters": clusters,
            "data_start": reserved + 2 * fat}


def _dir_label(label: str) -> bytes:
    return label.upper().encode("ascii", "replace")[:11].ljust(11, b" ")


def write_fat32(path, size_mb: int, label: str = LABEL) -> None:
    """Write an empty FAT32 volume of exactly `size_mb` MiB to `path` (raw image, no partition table)."""
    total = size_mb * MB // SECTOR
    g = fat32_layout(total)
    spc, reserved, fat, clusters = g["spc"], g["reserved"], g["fat_sectors"], g["clusters"]
    vol_id = int(time.time()) & 0xFFFFFFFF
    lab = _dir_label(label)

    boot = bytearray(SECTOR)
    boot[0:3] = b"\xEB\x58\x90"
    boot[3:11] = b"MSWIN4.1"
    # bytes/sector, sectors/cluster, reserved, FATs, root entries, total16, media, FAT16 size,
    # sectors/track, heads, hidden sectors, total sectors (32 bit)
    struct.pack_into("<HBHBHHBHHHII", boot, 11, SECTOR, spc, reserved, 2, 0, 0, 0xF8, 0, 63, 255, 0, total)
    struct.pack_into("<IHHIHH", boot, 36, fat, 0, 0, 2, 1, 6)       # FAT size, flags, version, root, FSInfo, backup
    boot[64] = 0x80                                                  # drive number
    boot[66] = 0x29                                                  # extended boot signature
    struct.pack_into("<I", boot, 67, vol_id)
    boot[71:82] = lab
    boot[82:90] = b"FAT32   "
    boot[510:512] = b"\x55\xAA"

    fsinfo = bytearray(SECTOR)
    struct.pack_into("<I", fsinfo, 0, 0x41615252)
    struct.pack_into("<I", fsinfo, 484, 0x61417272)
    struct.pack_into("<II", fsinfo, 488, clusters - 1, 3)            # free clusters (root uses one), next free
    struct.pack_into("<I", fsinfo, 508, 0xAA550000)

    fat_head = bytearray(SECTOR)
    struct.pack_into("<III", fat_head, 0, 0x0FFFFFF8, 0x0FFFFFFF, 0x0FFFFFFF)   # media, EOC, root dir (cluster 2)

    root = bytearray(SECTOR)                                         # first sector of the root directory cluster
    root[0:11] = lab
    root[11] = 0x08                                                  # volume label entry

    size = size_mb * MB
    with open(path, "wb") as f:
        f.truncate(size)                                             # everything not written below reads as zeros
        for off in (0, 6):                                           # boot sector + its backup
            f.seek(off * SECTOR)
            f.write(boot)
        for off in (1, 7):                                           # FSInfo + its backup
            f.seek(off * SECTOR)
            f.write(fsinfo)
        for n in range(2):                                           # both FAT copies
            f.seek((reserved + n * fat) * SECTOR)
            f.write(fat_head)
        f.seek(g["data_start"] * SECTOR)
        f.write(root)


# --------------------------------------------------------------------------- create / remove
def _mksdcard_exe():
    from . import sdk
    exe = sdk.emulator_exe().parent / ("mksdcard.exe" if system.IS_WIN else "mksdcard")
    return exe if exe.exists() else None


def _try_mksdcard(path: Path, size_mb: int) -> bool:
    exe = _mksdcard_exe()
    if exe is None:
        return False
    try:
        r = system.run_hidden([str(exe), "-l", LABEL, f"{size_mb}M", str(path)], timeout=300)
        ok = r.returncode == 0 and path.exists() and abs(path.stat().st_size - size_mb * MB) <= MB
    except Exception:                                  # noqa: BLE001 - missing / not runnable: use the built-in writer
        ok = False
    if not ok:
        _remove(path)
    return ok


def create_image(path, size_mb: int) -> str:
    """Create a blank SD card image. Returns which writer made it ("mksdcard" or "built-in"); raises OSError."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _remove(path)
    if _try_mksdcard(path, size_mb):
        return "mksdcard"
    write_fat32(path, size_mb)
    return "built-in"


def _remove(p: Path) -> None:
    try:
        if p.is_dir():
            def handler(func, q, _exc):
                try:
                    os.chmod(q, stat.S_IWRITE)
                    func(q)
                except OSError:
                    pass
            shutil.rmtree(p, onerror=handler)
        elif p.exists():
            try:
                p.unlink()
            except PermissionError:
                os.chmod(p, stat.S_IWRITE)
                p.unlink()
    except OSError:
        pass


def remove_card_files(avd_dir) -> None:
    """Remove the card image, its overlay and the saved snapshots (they remember the old card)."""
    d = Path(avd_dir)
    for name in (IMAGE, OVERLAY, "snapshots", "snapshots.img", "snapshots.img.qcow2"):
        _remove(d / name)
    for p in d.glob("*.lock"):
        if not p.is_dir():
            _remove(p)


# --------------------------------------------------------------------------- per-instance helpers
def image_path(inst) -> Path:
    return inst.avd_dir / IMAGE


def needs_prepare(inst) -> bool:
    """True when the instance wants an SD card whose image is missing or has another size than configured."""
    if inst.sd_mb <= 0:
        return False
    p = image_path(inst)
    try:
        return not p.is_file() or abs(p.stat().st_size - inst.sd_mb * MB) > MB
    except OSError:
        return True


def prepare(inst) -> str:
    """Make sure <avd>/sdcard.img exists with the configured size. A new card replaces the old one completely:
    overlay and snapshots go too. Returns "" when nothing had to be done, else the writer that made the card.
    Raises OSError with a plain-language message on failure (e.g. not enough free space)."""
    if not needs_prepare(inst):
        return ""
    need = inst.sd_mb
    free = system.free_mb(inst.avd_dir)
    if free < need + 256:
        raise OSError(f"Not enough free disk space for a {label_for(need)} SD card ({free:,} MB free). Lower the "
                      "SD card size in the instance's Settings, or free some space.")
    remove_card_files(inst.avd_dir)
    return create_image(image_path(inst), need)
