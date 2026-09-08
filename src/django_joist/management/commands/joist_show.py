"""Print the database structure as a terminal table: the text counterpart to
the visual dashboard. Structure only (table, column count, foreign-key
count), never row data; reads the same cached, exclusion-filtered snapshot
the diagram does."""

from __future__ import annotations

from django_joist.cli import JoistCommand

from django_joist.cache import schema_cache
from django_joist.selection import without_excluded_tables


class Command(JoistCommand):
    help = "Print the database structure as a table (structure only)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--database",
            default=None,
            help="Show this database alias instead of the default.",
        )

    def handle(self, *args, **options):
        cache = schema_cache()
        snapshot = cache.get(options["database"])
        if cache.last_error:
            self.stdout.write(
                self.style.WARNING(f"Cache unavailable ({cache.last_error}); snapshot built live.")
            )
        tables = without_excluded_tables(snapshot.get("tables", []), snapshot["connection"])

        if not tables:
            self.stdout.write(self.style.WARNING(f"No tables found for database [{snapshot['connection']}]."))
            return 0

        rows = [
            (t["name"], len(t.get("columns", [])), len(t.get("foreign_keys", [])))
            for t in tables
        ]
        header = ("Table", "Columns", "Foreign keys")
        widths = [max(len(h), *(len(str(r[i])) for r in rows)) for i, h in enumerate(header)]
        line = "+".join("-" * (w + 2) for w in widths)
        line = f"+{line}+"

        def fmt(row):
            return "| " + " | ".join(str(v).ljust(w) for v, w in zip(row, widths)) + " |"

        self.stdout.write(line)
        self.stdout.write(fmt(header))
        self.stdout.write(line)
        for row in rows:
            self.stdout.write(fmt(row))
        self.stdout.write(line)

        fallback = " (SQLite fallback)" if snapshot.get("fallback") else ""
        self.stdout.write(
            self.style.SUCCESS(f"{len(tables)} tables on [{snapshot['connection']}]{fallback}.")
        )
        self.stdout.write("See the diagram with manage.py joist_open.")
        return 0
