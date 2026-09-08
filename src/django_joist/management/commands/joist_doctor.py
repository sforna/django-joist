"""joist doctor: review the database structure for problems (structure only).

Exit codes: 0 clean (nothing at or above the fail level), 1 findings at or
above it, 2 a configuration or snapshot error. Safe in CI and commit hooks:
no row data, no network call.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

VALID_FORMATS = ("console", "json")
VALID_PRESETS = ("recommended", "strict", "none")
VALID_FAIL_ON = ("error", "warning", "info", "never")


class Command(BaseCommand):
    help = (
        "Review the database structure for problems visible from structure "
        "alone (missing primary keys, unindexed foreign keys, risky types). "
        "Structure only, never row data."
    )

    def add_arguments(self, parser):
        parser.add_argument("--database", default=None, help="Review this alias instead of the default.")
        parser.add_argument("--table", default=None, help="Review only this table.")
        parser.add_argument("--only", default=None, help="Only these categories, comma-separated (integrity,index,type).")
        parser.add_argument("--skip", default=None, help="Skip these categories, comma-separated.")
        parser.add_argument("--preset", default=None, help="recommended, strict, or none (defaults to config).")
        parser.add_argument("--format", default="console", help="console or json.")
        parser.add_argument(
            "--fail-on",
            dest="fail_on",
            default=None,
            help="error, warning, info, or never (defaults to config).",
        )

    def handle(self, *args, **options):
        from django_joist.conf import joist_settings

        fmt = str(options.get("format") or "console")
        preset = options.get("preset") or str(joist_settings.get("doctor.preset", "recommended"))
        fail_on = options.get("fail_on") or str(joist_settings.get("doctor.fail_on", "error"))

        if fmt not in VALID_FORMATS or preset not in VALID_PRESETS or fail_on not in VALID_FAIL_ON:
            self.stderr.write("Invalid --format, --preset, or --fail-on value.")
            return 2

        # Imported per call so tests can monkeypatch django_joist.cache.schema_cache.
        from django_joist.cache import schema_cache

        cache = schema_cache()
        try:
            snapshot = cache.get(options.get("database") or None)
        except Exception as exc:  # noqa: BLE001 - a snapshot error is exit 2, not a traceback
            self.stderr.write(f"Could not load the schema: {exc}")
            return 2

        # An unusable cache store is not a snapshot error: the review runs on
        # a live read. It used to land in the catch above and exit 2.
        self._warn_if_uncached(cache)

        from django_joist.doctor import findings_for
        from django_joist.doctor.formatters import ConsoleFormatter, JsonFormatter

        alias = snapshot["connection"]
        findings = findings_for(
            alias,
            snapshot,
            preset=preset,
            only=self._categories(options.get("only")),
            skip=self._categories(options.get("skip")),
            table=options.get("table") or None,
        )

        formatter = JsonFormatter() if fmt == "json" else ConsoleFormatter()
        for line in formatter.format(findings).rstrip("\n").splitlines():
            self.stdout.write(line)

        return self._exit_code(findings, fail_on)

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def _categories(value) -> list[str]:
        return [part.strip() for part in str(value or "").split(",") if part.strip()]

    def _warn_if_uncached(self, cache) -> None:
        """Shared notice for the read-only commands when the cache store was
        unusable and the structure was read live. They all still succeed -
        silence would be wrong, though, since the next run pays the same cost
        and the user has no other hint that the cache store is broken."""
        if cache.last_error:
            self.stdout.write(
                self.style.WARNING(
                    f"The cache store is unavailable, so the structure was read live: {cache.last_error}"
                )
            )
            self.stdout.write("Structure below is complete. Fix the cache store to make this fast again.")

    @staticmethod
    def _exit_code(findings, fail_on: str) -> int:
        if fail_on == "never":
            return 0
        from django_joist.doctor import Severity

        threshold = Severity(fail_on)
        for finding in findings:
            if finding.severity.meets_or_exceeds(threshold):
                return 1
        return 0
