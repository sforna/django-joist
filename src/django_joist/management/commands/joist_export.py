"""joist export: write the database structure to a standard format.

For CI, tooling, and version control. Exports the schema only — never row data — and no
network call beyond the local database, so it is safe in CI and commit hooks.

Writes to stdout by default so it pipes cleanly; --output writes a file. The
output is deterministic: the same schema always produces the same bytes,
which is what lets --check fail a build when a committed export file has gone
stale.

Exit codes: 0 written or (with --check) up to date; 1 --check found drift; 2
a usage or runtime error (unknown format, unmanaged alias, unwritable path,
--check without --output, or no tables matched the filters).
"""

from __future__ import annotations

import shlex
from pathlib import Path

from django.core.management.base import CommandError

from django_joist.cli import JoistCommand
from django_joist.conf import joist_settings


class Command(JoistCommand):
    help = "Export the database structure for CI and tooling (structure only)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--format",
            default=None,
            help="dbml, json, csv, markdown, mermaid, or llm (default: JOIST['export']['default_format']).",
        )
        parser.add_argument("--output", default=None, help="Write to this file instead of stdout.")
        parser.add_argument(
            "--database", default=None, help="Export this database alias instead of the first managed alias."
        )
        parser.add_argument("--tables", default="", help="Only these tables, comma-separated.")
        parser.add_argument(
            "--exclude", default="", help="Skip these tables, comma-separated (after --tables)."
        )
        parser.add_argument(
            "--focus", default=None, help="Reduce to this table and its foreign-key neighbourhood."
        )
        parser.add_argument(
            "--depth", type=int, default=None, help="Neighbourhood hops for --focus."
        )
        parser.add_argument(
            "--compact", action="store_true", help="Drop defaults and non-unique indexes."
        )
        parser.add_argument(
            "--no-annotations", action="store_true", help="Strip config/database annotations."
        )
        parser.add_argument(
            "--fresh", action="store_true", help="Rebuild the cached snapshot before exporting."
        )
        parser.add_argument(
            "--check", action="store_true", help="Exit 1 if --output would change; writes nothing."
        )

    def handle(self, *args, **options):
        from django_joist.cache import schema_cache
        from django_joist.export.builder import ExportBuilder
        from django_joist.export.exporter import SchemaExporter

        fmt = options["format"] or str(joist_settings.get("export.default_format", "dbml"))
        if not SchemaExporter.supports(fmt):
            raise CommandError(
                f"Unknown --format [{fmt}]. Supported: {', '.join(SchemaExporter.formats())}.",
                returncode=2,
            )

        check = bool(options["check"])
        output = options["output"]
        if check and output is None:
            raise CommandError(
                "--check requires --output: there is nothing to compare against.", returncode=2
            )

        alias = options["database"] or None
        cache = schema_cache()
        if alias is not None and alias not in cache.managed_aliases():
            raise CommandError(
                f"Connection [{alias}] is not managed by Joist. Add it under JOIST['connections'].",
                returncode=2,
            )

        # The command is a thin CLI wrapper over the shared export pipeline.
        builder = (
            ExportBuilder(cache=cache)
            .only(self._list(options["tables"]))
            .exclude(self._list(options["exclude"]))
        )
        if alias is not None:
            builder = builder.connection(alias)
        if options["focus"]:
            builder = builder.focus(str(options["focus"]), options["depth"])
        if options["compact"]:
            builder = builder.compact()
        if options["no_annotations"]:
            builder = builder.without_annotations()
        if options["fresh"]:
            builder = builder.fresh()

        try:
            builder.to_array()
        except ValueError as exc:
            # No tables matched / focus root missing (the alias is pre-validated).
            raise CommandError(str(exc), returncode=2) from exc
        except Exception as exc:  # a dead database is a runtime error here
            raise CommandError(f"Could not load the schema: {exc}", returncode=2) from exc

        # Written to stderr, not stdout: without --output the export itself
        # goes to stdout and is piped, so a notice there would corrupt the
        # artifact. The exit code stays driven by drift alone, so an unrelated
        # cache outage can never turn a --check gate in CI red.
        if cache.last_error:
            self.stderr.write(
                self.style.WARNING(f"The cache store is unavailable, so the schema was read live: {cache.last_error}")
            )

        content = builder.render(fmt)

        if check:
            return self._check(str(output), content, self._regenerate_command(options, fmt))
        if output is not None:
            return self._write(str(output), content, fmt)

        self.stdout.write(content, ending="")
        return 0

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _list(value) -> list[str]:
        """Parse a comma-separated option into a trimmed, non-empty list."""
        return [part for part in (v.strip() for v in str(value or "").split(",")) if part]

    @classmethod
    def _regenerate_command(cls, options, fmt: str) -> str:
        """The command line that rewrites --output with this run's settings.

        Repeats every option that shapes the content - the resolved format
        included - so following the hint makes the next --check pass rather
        than rewriting the file in the default format. --fresh is left out:
        it changes when the schema is read, never what is written.
        """
        parts = ["manage.py", "joist_export", f"--format={fmt}", f"--output={options['output']}"]
        if options["database"]:
            parts.append(f"--database={options['database']}")
        if tables := cls._list(options["tables"]):
            parts.append(f"--tables={','.join(tables)}")
        if exclude := cls._list(options["exclude"]):
            parts.append(f"--exclude={','.join(exclude)}")
        if options["focus"]:
            parts.append(f"--focus={options['focus']}")
            if options["depth"] is not None:
                parts.append(f"--depth={options['depth']}")
        if options["compact"]:
            parts.append("--compact")
        if options["no_annotations"]:
            parts.append("--no-annotations")
        return shlex.join(parts)

    def _check(self, output: str, content: str, regenerate: str) -> int:
        path = Path(output)
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current == content:
            self.stdout.write(self.style.SUCCESS(f"{output} is up to date."))
            return 0
        self.stderr.write(
            self.style.ERROR(
                f"{output} is out of date. Regenerate it with: {regenerate}"
            )
        )
        return 1

    def _write(self, output: str, content: str, fmt: str) -> int:
        try:
            Path(output).write_text(content, encoding="utf-8")
        except OSError as exc:
            raise CommandError(f"Could not write to [{output}]: {exc}", returncode=2) from exc
        self.stdout.write(self.style.SUCCESS(f"Wrote {fmt} export to {output}."))
        return 0
