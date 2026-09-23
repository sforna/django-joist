"""Assembles and runs the doctor for one alias.

Injects the live driver into the snapshot, drops excluded tables, resolves
the active rule set from the preset and config, and runs the rules with the
configured severity overrides and ignore patterns. Both the ``joist_doctor``
command and the dashboard schema endpoint go through here, so the CLI and
the browser see identical findings.

Structure only: it works on the schema snapshot and never touches row data.
"""

from __future__ import annotations

from typing import Any, Iterable

from ..conf import joist_settings
from ..selection import excluded_tables_for
from .collection import FindingCollection
from .enums import Confidence, Severity
from .registry import RuleRegistry
from .runner import DoctorRunner


class DoctorReport:
    def __init__(self, runner: DoctorRunner | None = None) -> None:
        self.runner = runner or DoctorRunner()

    def for_snapshot(
        self,
        alias: str,
        snapshot: dict[str, Any],
        preset: str | None = None,
        only: Iterable[str] = (),
        skip: Iterable[str] = (),
        table: str | None = None,
    ) -> dict[str, Any]:
        """Run the doctor and return the JSON-ready payload directly.

        This is the contract the dashboard schema endpoint and the CLI both
        consume: ``{"summary": {...}, "findings": [...]}`` with every finding
        carrying its confidence and category so a client can mark heuristics
        and group without a second lookup.
        """
        return self._to_array(self._run(alias, snapshot, preset, only, skip, table))

    # -- internals ---------------------------------------------------------
    def _run(
        self,
        alias: str,
        snapshot: dict[str, Any],
        preset: str | None = None,
        only: Iterable[str] = (),
        skip: Iterable[str] = (),
        table: str | None = None,
    ) -> FindingCollection:
        preset = preset or str(joist_settings.get("doctor.preset", "recommended"))

        snapshot = dict(snapshot)
        # The live vendor even for a fallback snapshot, as the reference does:
        # the findings are about the alias's real database. The one rule that
        # reads the replay's SQLite type names (JOIST-INT-003) checks the
        # snapshot's own ``fallback`` flag for that.
        snapshot["driver"] = self._driver_for(alias)
        snapshot["tables"] = self._select_tables(snapshot.get("tables", []), alias, table)

        rules = RuleRegistry.default().resolve(
            preset, list(only), list(skip), self._enabled_overrides()
        )

        return self.runner.run(
            rules,
            snapshot,
            alias,
            self._severity_overrides(),
            {str(k): list(v or []) for k, v in (joist_settings.get("doctor.ignore", {}) or {}).items()},
        )

    @staticmethod
    def _driver_for(alias: str) -> str:
        try:
            from django.db import connections

            return connections[alias].vendor
        except Exception:  # noqa: BLE001 - driver is an enrichment, never fatal
            return ""

    @staticmethod
    def _select_tables(tables: list[dict], alias: str, only: str | None) -> list[dict]:
        excluded = set(excluded_tables_for(alias)) | set(joist_settings.get("doctor.exclude", []) or [])
        return [
            t
            for t in tables
            if t.get("name") not in excluded and (only is None or t.get("name") == only)
        ]

    @staticmethod
    def _enabled_overrides() -> dict[str, bool]:
        """JOIST['doctor']['rules'] as a code => on/off map (False disables;
        True or a severity override enables)."""
        overrides = {}
        for code, value in (joist_settings.get("doctor.rules", {}) or {}).items():
            overrides[str(code)] = value is not False
        return overrides

    @staticmethod
    def _severity_overrides() -> dict[str, Severity]:
        overrides = {}
        for code, value in (joist_settings.get("doctor.rules", {}) or {}).items():
            if isinstance(value, dict) and value.get("severity"):
                overrides[str(code)] = Severity(str(value["severity"]))
        return overrides

    # -- serialization -------------------------------------------------------
    def _to_array(self, findings: FindingCollection) -> dict[str, Any]:
        meta = self._rule_metadata()
        return {
            "summary": self._summary(findings),
            "findings": [
                {
                    "code": f.code,
                    "severity": f.severity.value,
                    "connection": f.connection,
                    "table": f.table,
                    "column": f.column,
                    "message": f.message,
                    "hint": f.hint,
                    "suggestion": f.suggestion,
                    "confidence": meta.get(f.code, {}).get("confidence", Confidence.HIGH.value),
                    "category": meta.get(f.code, {}).get("category"),
                    "fingerprint": f.fingerprint(),
                }
                for f in findings.all()
            ],
        }

    @staticmethod
    def _summary(findings: FindingCollection) -> dict[str, int]:
        summary = {"total": len(findings), "error": 0, "warning": 0, "info": 0}
        for finding in findings:
            summary[finding.severity.value] += 1
        return summary

    @staticmethod
    def _rule_metadata() -> dict[str, dict[str, str]]:
        """Rule code => confidence and category, read once from the default
        registry."""
        return {
            rule.code: {"confidence": rule.confidence.value, "category": rule.category.value}
            for rule in RuleRegistry.default().all()
        }


def findings_for(
    alias: str,
    snapshot: dict,
    preset: str | None = None,
    only: Iterable[str] = (),
    skip: Iterable[str] = (),
    table: str | None = None,
) -> FindingCollection:
    """The raw collection, for the formatters in the CLI."""
    return DoctorReport()._run(alias, snapshot, preset, only, skip, table)
