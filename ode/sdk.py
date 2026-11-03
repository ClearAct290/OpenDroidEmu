"""Talks to Google's Android SDK repository: finds the emulator / platform-tools /
system images, downloads them (sha1-verified) and unpacks them into core/."""
from __future__ import annotations

import hashlib
import html
import os
import platform
import re
import shutil
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import APP_VERSION, paths, system

REPO_BASE = "https://dl.google.com/android/repository/"
RELEASE_NOTES_URL = "https://developer.android.com/studio/releases/emulator"
USER_AGENT = f"OpenDroidEmu/{APP_VERSION} (Android SDK repository client)"
HOST_OS = "windows" if system.IS_WIN else "macosx" if system.IS_MAC else "linux"

# flavor id -> (display name, repository sub-folder)
FLAVORS = {
    "google_apis": ("Google APIs", "sys-img/google_apis/"),
    "google_apis_playstore": ("Google Play Store", "sys-img/google_apis_playstore/"),
    "default": ("AOSP (plain Android)", "sys-img/android/"),
}

ANDROID_NAMES = {
    8: "2.2 Froyo", 9: "2.3 Gingerbread", 10: "2.3.3 Gingerbread", 11: "3.0 Honeycomb",
    12: "3.1 Honeycomb", 13: "3.2 Honeycomb", 14: "4.0 Ice Cream Sandwich",
    15: "4.0.3 Ice Cream Sandwich", 16: "4.1 Jelly Bean", 17: "4.2 Jelly Bean",
    18: "4.3 Jelly Bean", 19: "4.4 KitKat", 21: "5.0 Lollipop", 22: "5.1 Lollipop",
    23: "6.0 Marshmallow", 24: "7.0 Nougat", 25: "7.1 Nougat", 26: "8.0 Oreo", 27: "8.1 Oreo",
    28: "9 Pie", 29: "10", 30: "11", 31: "12", 32: "12L", 33: "13", 34: "14", 35: "15",
    36: "16", 37: "17",
}


# ------------------------------------------------------------------------ model
@dataclass
class Package:
    path: str
    revision: tuple
    display: str
    url: str
    size: int
    sha1: str
    channel: str = "channel-0"
    api: int = 0
    abi: str = ""
    tag: str = ""
    api_label: str = ""
    sort_key: tuple = ()

    @property
    def rev_str(self) -> str:
        return ".".join(str(x) for x in self.revision)

    @property
    def size_mb(self) -> float:
        return self.size / 1048576.0


@dataclass
class CoreInfo:
    emulator: Package
    platform_tools: Package


@dataclass
class Job:
    """One zip to download and install into `target`."""
    name: str
    url: str
    size: int
    sha1: str
    target: Path


class Cancelled(Exception):
    pass


# --------------------------------------------------------------------- network
def http_get(url: str, timeout: float = 25) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _fetch_repo(subdir: str, stem: str):
    """Return (url, xml bytes). Tries newer schema numbers first and falls back to the
    cached copy of the last successful download when offline."""
    last_err = None
    for ver in (3, 2, 1):
        name = f"{stem}-{ver}.xml"
        url = REPO_BASE + subdir + name
        cache = paths.CACHE_DIR / (subdir.replace("/", "_") + name)
        try:
            data = http_get(url)
            cache.write_bytes(data)
            return url, data
        except urllib.error.HTTPError as exc:      # that schema number doesn't exist - try the next
            last_err = exc
            continue
        except Exception as exc:                  # offline / DNS / timeout
            last_err = exc
            break
    for ver in (3, 2, 1):
        name = f"{stem}-{ver}.xml"
        cache = paths.CACHE_DIR / (subdir.replace("/", "_") + name)
        if cache.exists():
            return REPO_BASE + subdir + name, cache.read_bytes()
    raise ConnectionError(f"Couldn't reach Google's SDK servers ({last_err}). "
                          "Please check your internet connection.")


def _host_arches() -> set:
    if platform.machine().lower() in ("arm64", "aarch64"):
        return {"aarch64", "arm64"}
    return {"", "x64", "x86_64", "amd64"}


def _pick_archive(rp, arches):
    cands = []
    for ar in rp.findall("archives/archive"):
        host_os = (ar.findtext("host-os") or "").strip()
        if host_os and host_os != HOST_OS:
            continue
        cands.append((ar, (ar.findtext("host-arch") or "").strip().lower()))
    if not cands:
        return None
    for ar, arch in cands:
        if arch in arches:
            return ar
    return cands[0][0]


_SECOND = re.compile(r"^android-(\d+)(?:\.(\d+))?(?:-ext(\d+))?")


def _api_info(path: str):
    """'system-images;android-34-ext10;google_apis;x86_64' -> (api, label, sort_key)"""
    parts = path.split(";")
    m = _SECOND.match(parts[1]) if len(parts) > 1 else None
    if not m:
        return 0, "", ()
    api, minor, ext = int(m.group(1)), m.group(2), m.group(3)
    txt = f"API {api}" + (f".{minor}" if minor else "") + (f", ext {ext}" if ext else "")
    name = ANDROID_NAMES.get(api)
    label = f"Android {name} ({txt})" if name else f"Android ({txt})"
    return api, label, (api, int(minor or 0), int(ext or 0))


def _parse_packages(data: bytes, base_url: str) -> list:
    root = ET.fromstring(data)
    for el in root.iter():                       # drop XML namespaces
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    arches = _host_arches()
    out = []
    for rp in root.iter("remotePackage"):
        path = rp.get("path", "")
        rev_el = rp.find("revision")
        rev = tuple(int((rev_el.findtext(k) or "0").strip() or 0)
                    for k in ("major", "minor", "micro")) if rev_el is not None else (0,)
        chan_el = rp.find("channelRef")
        channel = chan_el.get("ref", "channel-0") if chan_el is not None else "channel-0"
        archive = _pick_archive(rp, arches)
        comp = archive.find("complete") if archive is not None else None
        if comp is None:
            continue
        url = (comp.findtext("url") or "").strip()
        if not url:
            continue
        ck = comp.find("checksum")
        pkg = Package(path=path, revision=rev, display=(rp.findtext("display-name") or path).strip(),
                      url=urllib.parse.urljoin(base_url, url),
                      size=int((comp.findtext("size") or "0").strip() or 0),
                      sha1=(ck.text or "").strip() if ck is not None else "",
                      channel=channel)
        if path.startswith("system-images;"):
            td = rp.find("type-details")
            if td is None or (td.findtext("codename") or "").strip():
                continue                          # skip previews
            pkg.abi = (td.findtext("abi") or "").strip()
            tag_el = td.find("tag")
            pkg.tag = (tag_el.findtext("id") or "").strip() if tag_el is not None else ""
            pkg.api, pkg.api_label, pkg.sort_key = _api_info(path)
            if not pkg.api:
                continue
        out.append(pkg)
    return out


def _best(pkgs, path):
    cands = [p for p in pkgs if p.path == path]
    stable = [p for p in cands if p.channel == "channel-0"] or cands
    return max(stable, key=lambda p: p.revision) if stable else None


_CACHE: dict = {}


def _cached(key, ttl, fn):
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _CACHE[key] = (time.time(), val)
    return val


def core_info() -> CoreInfo:
    """Latest stable emulator + platform-tools for this OS."""
    def load():
        url, data = _fetch_repo("", "repository2")
        pkgs = _parse_packages(data, url)
        emu, pt = _best(pkgs, "emulator"), _best(pkgs, "platform-tools")
        if not emu or not pt:
            raise RuntimeError("Google's repository has no emulator package for this system.")
        return CoreInfo(emu, pt)
    return _cached("core", 300, load)


def get_system_images(flavor: str) -> list:
    """x86 / x86_64 / arm64-v8a stable images of one flavor, oldest -> newest."""
    def load():
        _label, sub = FLAVORS[flavor]
        url, data = _fetch_repo(sub, "sys-img2")
        best: dict = {}
        for p in _parse_packages(data, url):
            if (p.path.startswith("system-images;") and p.abi in ("x86", "x86_64", "arm64-v8a")
                    and p.tag == flavor and p.channel == "channel-0"):
                if p.path not in best or p.revision > best[p.path].revision:
                    best[p.path] = p
        return sorted(best.values(), key=lambda p: (p.sort_key, p.abi))
    return _cached("img:" + flavor, 300, load)


# ------------------------------------------------------------------- install state
def emulator_exe() -> Path:
    return paths.CORE_DIR / "emulator" / ("emulator.exe" if system.IS_WIN else "emulator")


def adb_exe() -> Path:
    return paths.CORE_DIR / "platform-tools" / ("adb.exe" if system.IS_WIN else "adb")


def core_installed() -> bool:
    return emulator_exe().exists()


def pkg_dir(pkg_path: str) -> Path:
    return paths.CORE_DIR.joinpath(*pkg_path.split(";"))


def installed_revision(pkg_path: str):
    f = pkg_dir(pkg_path) / "source.properties"
    try:
        for line in f.read_text(errors="replace").splitlines():
            if line.startswith("Pkg.Revision="):
                nums = [int(x) for x in re.findall(r"\d+", line.split("=", 1)[1])]
                return tuple(nums) if nums else None
    except OSError:
        pass
    return None


def image_installed(pkg_path: str) -> bool:
    d = pkg_dir(pkg_path)
    return (d / "system.img").exists() or (d / "source.properties").exists()


def rev_newer(remote: tuple, local: tuple) -> bool:
    pad = lambda t: tuple(list(t) + [0] * (4 - len(t)))      # noqa: E731
    return pad(remote) > pad(local)


def job_for(pkg: Package, name: str = "") -> Job:
    return Job(name or pkg.display, pkg.url, pkg.size, pkg.sha1, pkg_dir(pkg.path))


# --------------------------------------------------------------- download / install
def download(job: Job, dest: Path, on_bytes, cancelled) -> None:
    req = urllib.request.Request(job.url, headers={"User-Agent": USER_AGENT})
    sha = hashlib.sha1()
    with urllib.request.urlopen(req, timeout=30) as resp, open(dest, "wb") as out:
        while True:
            if cancelled():
                raise Cancelled()
            chunk = resp.read(128 * 1024)
            if not chunk:
                break
            out.write(chunk)
            sha.update(chunk)
            on_bytes(len(chunk))
    if job.sha1 and sha.hexdigest().lower() != job.sha1.lower():
        raise RuntimeError(f"The download of {job.name} is corrupted (checksum mismatch). Please try again.")


def install_zip(job: Job, zip_path: Path, on_progress, cancelled) -> None:
    """Extract to a temp folder, then swap it into place (replaces any old version)."""
    tmp = paths.EXTRACT_DIR / (re.sub(r"\W+", "_", job.target.name) + "_tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            infos = zf.infolist()
            total = sum(i.file_size for i in infos) or 1
            done = 0
            for info in infos:
                if cancelled():
                    raise Cancelled()
                zf.extract(info, tmp)
                mode = info.external_attr >> 16
                if mode and not system.IS_WIN and not info.is_dir():
                    try:
                        os.chmod(tmp / info.filename, stat.S_IMODE(mode) | 0o600)
                    except OSError:
                        pass
                done += info.file_size
                on_progress(done / total)
        entries = list(tmp.iterdir())
        src = entries[0] if len(entries) == 1 and entries[0].is_dir() else tmp
        if job.target.exists():
            try:
                shutil.rmtree(job.target)
            except OSError as exc:
                raise RuntimeError(f"Couldn't replace the old files ({exc}). "
                                   "Close any running emulators and try again.")
        job.target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(job.target))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------- changelog
_HEAD = re.compile(r"^(\d+\.\d+\.\d+)\s+(Stable|Patch|Canary|Beta|RC\d*|Preview)\b", re.I)


def _html_to_lines(raw: str) -> list:
    raw = re.sub(r"(?is)<(script|style|nav|footer)\b.*?</\1>", "", raw)
    raw = re.sub(r"(?i)<li[^>]*>", "\n\u2022 ", raw)
    raw = re.sub(r"(?i)</?(p|div|h[1-6]|ul|ol|tr|br|section|article|table)\b[^>]*>", "\n", raw)
    raw = html.unescape(re.sub(r"<[^>]+>", "", raw))
    lines = [re.sub(r"[ \t\u00a0]+", " ", ln).strip() for ln in raw.splitlines()]
    return [ln for ln in lines if ln]


def fetch_changelog(version: str) -> str:
    """Release notes of one emulator version, scraped from developer.android.com."""
    try:
        lines = _html_to_lines(http_get(RELEASE_NOTES_URL, 20).decode("utf-8", "replace"))
    except Exception:
        return f"The release notes couldn't be loaded right now.\n\nSee: {RELEASE_NOTES_URL}"
    sections = []
    for ln in lines:
        m = _HEAD.match(ln)
        if m:
            sections.append([m.group(1), ln, []])
        elif sections:
            sections[-1][2].append(ln)
    pool = [s for s in sections if s[0] == version and s[2]]
    pool = pool or [s for s in sections if "stable" in s[1].lower() and s[2]] or [s for s in sections if s[2]]
    if not pool:
        return f"No release notes found for {version}.\n\nSee: {RELEASE_NOTES_URL}"
    pick = max(pool, key=lambda s: len(s[2])) if pool[0][0] == version else pool[0]
    body = "\n".join(pick[2][:60])
    return f"{pick[1]}\n\n{body[:5000]}\n\nFull notes: {RELEASE_NOTES_URL}"


def accel_check():
    """(ok, output) of `emulator -accel-check` (is a hypervisor available?)."""
    exe = emulator_exe()
    if not exe.exists():
        return False, "Emulator core is not installed."
    try:
        r = system.run_hidden([str(exe), "-accel-check"], timeout=25)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as exc:
        return False, str(exc)
