"""Boots the test project for the browser lane.

A real dev server rather than a static harness: the page, its assets, the JSON
endpoint, the asset allow-list and the export route are the ones a host mounts,
so what the browser exercises is the shipped app rather than a copy of it. That
also keeps the markup in one place - there is no harness to drift from
``index.html``.

Two fixtures make the browser-only behaviour observable, and both are structure
only (Joist never reads rows):

* a table that exists only in the secondary database, so switching connection
  visibly changes the diagram;
* a diff baseline captured with one table missing, so the Changes panel has
  something to report.

Run it with the interpreter that has Django and this package installed:

    python tests/browser/serve.py
"""

import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for path in (ROOT / "src", ROOT):
    sys.path.insert(0, str(path))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.browser.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.db import connections  # noqa: E402

#: The table only the secondary alias has, so a connection switch is visible.
SECONDARY_ONLY = "joist_secondary_only"
#: The table the seeded baseline pretends was added by the last migration.
BASELINE_MISSING = "testapp_tag"


def reset_state() -> None:
    for config in settings.DATABASES.values():
        Path(config["NAME"]).unlink(missing_ok=True)
    diff_dir = settings.JOIST.get("diff", {}).get("dir", "")
    shutil.rmtree(diff_dir, ignore_errors=True)
    # Both are created on demand: SQLite will not create a missing directory,
    # and the diff store writes baselines/<alias>.json inside its own.
    for directory in [Path(config["NAME"]).parent for config in settings.DATABASES.values()] + [diff_dir]:
        Path(directory).mkdir(parents=True, exist_ok=True)


def migrate() -> None:
    for alias in settings.DATABASES:
        call_command("migrate", database=alias, verbosity=0, run_syncdb=True)

    with connections["secondary"].cursor() as cursor:
        cursor.execute(f"CREATE TABLE {SECONDARY_ONLY} (id integer)")

    # The post_migrate listener already cached a snapshot per managed alias,
    # before the extra table existed (a migrate is the only thing that
    # refreshes the cache, and this change is deliberately outside it). Drop
    # them so the browser is served the schema that is actually on disk.
    from django_joist.cache import schema_cache

    cache = schema_cache()
    for alias in settings.DATABASES:
        cache.forget(alias)


def seed_baseline() -> None:
    from django_joist.cache import schema_cache
    from django_joist.diff.baseline import BaselineStore

    snapshot = schema_cache().rebuild("default")
    baseline = json.loads(json.dumps(snapshot))
    baseline["tables"] = [t for t in baseline["tables"] if t["name"] != BASELINE_MISSING]
    BaselineStore().save("default", baseline)


def main() -> None:
    reset_state()
    migrate()
    seed_baseline()
    call_command(
        "runserver",
        f"127.0.0.1:{os.environ.get('JOIST_BROWSER_PORT', '8899')}",
        "--noreload",
        verbosity=0,
    )


if __name__ == "__main__":
    main()
