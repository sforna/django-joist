"""Rebuild the cached schema snapshot - for CI, seeding workflows, or forcing
a refresh. Works regardless of the enabled switch.

Everywhere else a broken cache store degrades quietly, but this command
exists to write the snapshot: saying "rebuilt" when nothing was stored would
hide the one problem the user ran it to fix, so a failed store exits non-zero.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from django_joist.cache import schema_cache


class Command(BaseCommand):
    help = "Rebuild the cached Joist schema snapshot."

    def add_arguments(self, parser):
        parser.add_argument(
            "--database",
            default=None,
            help="Rebuild only this database alias instead of all managed ones.",
        )

    def handle(self, *args, **options):
        cache = schema_cache()
        aliases = [options["database"]] if options["database"] else cache.managed_aliases()

        failed = False
        for alias in aliases:
            snapshot = cache.rebuild(alias)
            if cache.last_error:
                self.stderr.write(
                    f"Built the schema snapshot for [{alias}] but could not cache it: {cache.last_error}"
                )
                failed = True
                continue
            note = " (SQLite fallback)" if snapshot.get("fallback") else ""
            self.stdout.write(self.style.SUCCESS(f"Rebuilt schema snapshot for [{alias}]{note}."))

        if failed:
            self.stdout.write("Check your cache backend (CACHES), then run this again.")
            return 1
        return 0
