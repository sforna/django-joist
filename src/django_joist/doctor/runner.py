"""Runs a resolved set of rules against one snapshot.

This is where the config-driven concerns live, so rules stay pure: per-code
severity overrides and ignore patterns. Rule selection (presets, --only,
--skip, enable/disable) happens before this and is handed in as the already
resolved rule list.
"""

from __future__ import annotations

from fnmatch import fnmatch
from typing import Iterable

from .collection import FindingCollection
from .enums import Severity
from .finding import Finding
from .rules.base import Rule


class DoctorRunner:
    def run(
        self,
        rules: Iterable[Rule],
        snapshot: dict,
        connection: str,
        severity_overrides: dict[str, Severity] | None = None,
        ignore: dict[str, list[str]] | None = None,
    ) -> FindingCollection:
        severity_overrides = severity_overrides or {}
        ignore = ignore or {}

        findings: list[Finding] = []
        for rule in rules:
            for finding in rule.check(snapshot, connection):
                if finding.code in severity_overrides:
                    finding = finding.with_severity(severity_overrides[finding.code])
                if self._is_ignored(finding, ignore):
                    continue
                findings.append(finding)

        return FindingCollection(findings).sorted()

    @staticmethod
    def _is_ignored(finding: Finding, ignore: dict[str, list[str]]) -> bool:
        """True when the finding matches an ignore pattern registered under its
        own rule code. A pattern is fnmatch'd against the table and, when the
        finding has a column, against "table.column"."""
        for pattern in ignore.get(finding.code) or []:
            if fnmatch(finding.table, pattern):
                return True
            if finding.column is not None and fnmatch(f"{finding.table}.{finding.column}", pattern):
                return True
        return False
