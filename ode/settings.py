from __future__ import annotations

import json

from . import paths


class Settings:
    DEFAULTS = {"theme": "light", "show_guide": True}

    def __init__(self):
        self.data = dict(self.DEFAULTS)
        try:
            self.data.update(json.loads(paths.SETTINGS_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass

    def get(self, key, default=None):
        return self.data.get(key, self.DEFAULTS.get(key, default))

    def set(self, key, value):
        self.data[key] = value
        try:
            paths.SETTINGS_FILE.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except OSError:
            pass
