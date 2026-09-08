"""joist diff: what changed in the structure since the last migration."""

from __future__ import annotations

from django_joist.cli import JoistCommand

from django_joist.conf import joist_settings


class Command(JoistCommand):
    help = (
        "Show what changed in the database structure since the last migration "
        "(structure only, safe in CI)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--database",
            dest="database",
            default=None,
            help="Diff this database alias instead of the default.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit the raw diff as JSON instead of a human-readable report.",
        )

    def handle(self, *args, **options):
        import json as _json

        from django_joist.cache import schema_cache
        from django_joist.diff.differ import SchemaDiffer

        if not joist_settings.get("diff.enabled", True):
            self.stdout.write(
                self.style.WARNING(
                    "Schema diff is disabled. Set JOIST['diff']['enabled'] = True to record a baseline."
                )
            )
            return 0

        cache = schema_cache()
        current = cache.get(options["database"])
        if cache.last_error:
            self.stdout.write(
                self.style.WARNING(f"Cache unavailable ({cache.last_error}); snapshot built live.")
            )
        alias = current["connection"]

        from django_joist.diff.baseline import BaselineStore

        baselines = BaselineStore()
        baseline = baselines.get(alias)

        if baseline is None:
            if baselines.last_error:
                self.stdout.write(
                    self.style.WARNING(f"Could not read the diff baseline: {baselines.last_error}")
                )
                self.stdout.write(
                    "Set JOIST['diff']['dir'] to a writable directory, or disable the "
                    "feature with JOIST['diff']['enabled'] = False."
                )
                return 0
            self.stdout.write(self.style.WARNING(f"No baseline recorded for [{alias}] yet."))
            self.stdout.write("A baseline is captured on the next migration while Joist is enabled.")
            return 0

        diff = SchemaDiffer().diff(baseline, current)

        if options["json"]:
            self.stdout.write(_json.dumps(diff, indent=2, sort_keys=True))
            return 0

        if not diff["has_changes"]:
            self.stdout.write(
                self.style.SUCCESS(f"No structural changes on [{alias}] since the last migration.")
            )
            return 0

        self.stdout.write(f"Schema changes on {self.style.MIGRATE_HEADING(alias)} since the last migration:")
        self._print_list("Added tables", "+", diff["tables_added"])
        self._print_list("Removed tables", "-", diff["tables_removed"])

        if diff["tables_changed"]:
            self.stdout.write("")
            self.stdout.write(self.style.MIGRATE_HEADING("Changed tables:"))
            for table in diff["tables_changed"]:
                self.stdout.write(f"  ~ {table['name']}")
                for line in self._describe_table(table):
                    self.stdout.write(f"      {line}")

        return 0

    # -- rendering ---------------------------------------------------------
    def _print_list(self, heading, marker, items):
        if not items:
            return
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(f"{heading}:"))
        for item in items:
            self.stdout.write(f"  {marker} {item['name']}")

    def _describe_table(self, table):
        lines = []
        for col in table["columns_added"]:
            lines.append(f"column added: {col['name']} ({col['type']})")
        for col in table["columns_removed"]:
            lines.append(f"column removed: {col['name']}")
        for col in table["columns_changed"]:
            lines.append(f"column changed: {col['name']} ({self._describe_changes(col['changes'])})")
        for idx in table["indexes_added"]:
            lines.append(f"index added: {idx['name']}")
        for idx in table["indexes_removed"]:
            lines.append(f"index removed: {idx['name']}")
        for idx in table["indexes_changed"]:
            lines.append(f"index changed: {idx['name']}")
        for fk in table["foreign_keys_added"]:
            lines.append(f"foreign key added: {fk['name']}")
        for fk in table["foreign_keys_removed"]:
            lines.append(f"foreign key removed: {fk['name']}")
        for fk in table["foreign_keys_changed"]:
            lines.append(f"foreign key changed: {fk['name']}")
        pk = table.get("changes", {}).get("primary_key")
        if pk:
            lines.append(
                "primary key: [{}] -> [{}]".format(", ".join(pk["before"]), ", ".join(pk["after"]))
            )
        return lines

    def _describe_changes(self, changes):
        return ", ".join(
            f"{field}: {self._scalar(c['before'])} -> {self._scalar(c['after'])}"
            for field, c in changes.items()
        )

    @staticmethod
    def _scalar(value) -> str:
        if value is None:
            return "null"
        if value is True:
            return "true"
        if value is False:
            return "false"
        if isinstance(value, (list, tuple)):
            return "[" + ", ".join(str(v) for v in value) + "]"
        return str(value)
