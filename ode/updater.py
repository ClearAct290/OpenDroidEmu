"""ODE's own update check: reads version.json from the project's GitHub repository.

version.json sits in the root of the repo and looks like  {"version": "1.0.1"}.
ODE never downloads or installs anything itself - it only tells the user to go to GitHub.
"""
from __future__ import annotations

import json
import re
import urllib.request

from . import APP_NAME, APP_VERSION, VERSION_URL

_VERSION_RE = re.compile(r"\d+(\.\d+){0,3}")


def parse_version(text) -> tuple:
    """'1.0.1' -> (1, 0, 1). Anything that isn't a number is ignored ('v1.2' -> (1, 2))."""
    return tuple(int(x) for x in re.findall(r"\d+", str(text))[:4])


def is_newer(remote, local=APP_VERSION) -> bool:
    a, b = parse_version(remote), parse_version(local)
    n = max(len(a), len(b), 3)
    pad = lambda t: t + (0,) * (n - len(t))          # noqa: E731
    return pad(a) > pad(b)


def fetch_remote_version(timeout: float = 8) -> str:
    """The version string published in version.json on GitHub. Raises on network / format errors."""
    req = urllib.request.Request(VERSION_URL, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}",
                                                       "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8-sig"))
    version = str(data.get("version", "")).strip() if isinstance(data, dict) else ""
    if not _VERSION_RE.fullmatch(version):
        raise ValueError("version.json doesn't contain a valid version number.")
    return version


def check_for_update():
    """The newer version string if GitHub has one, else None. Raises when GitHub can't be reached."""
    remote = fetch_remote_version()
    return remote if is_newer(remote) else None
