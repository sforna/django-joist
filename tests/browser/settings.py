"""Browser-lane settings: the test project on file-backed SQLite.

The dev server needs a database that outlives a single connection (Joist
introspects it live), and the diff feature needs a writable directory. Both are
throwaway files under ``tests/browser/.state/``, recreated on every server start.
"""

import os
from pathlib import Path

from tests.settings import *  # noqa: F401,F403

STATE = Path(os.environ.get("JOIST_BROWSER_STATE", Path(__file__).resolve().parent / ".state"))

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(STATE / "browser.sqlite3"),
    },
    "secondary": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(STATE / "browser-secondary.sqlite3"),
    },
}

JOIST = {
    # Both aliases are managed, so the dashboard offers the connection switcher.
    "connections": {"default": {}, "secondary": {}},
    "diff": {"dir": str(STATE / "var")},
}
