"""Finding renderers for the CLI: a plain-text table and structured JSON.

Both are deliberately free of ANSI colour, so the command can style them and
the output is stable to snapshot in tests. The JSON shape is shared with the
reference so CI tooling reads either.
"""

from __future__ import annotations

import json
import textwrap

from .collection import FindingCollection
from .finding import Finding


class ConsoleFormatter:
    """A one-line summary, then findings grouped by table: a header row per
    table, then severity / code / column / message. Long messages wrap inside
    their column so the table stays a comfortable width."""

    MESSAGE_WIDTH = 60

    def format(self, findings: FindingCollection) -> str:
        if findings.is_empty():
            return "Joist doctor: no findings.\n"

        lines = [self._summary_line(findings), ""]

        grouped: dict[str, list[Finding]] = {}
        for finding in findings:
            grouped.setdefault(finding.table, []).append(finding)

        for i, (table_name, table_findings) in enumerate(grouped.items()):
            if i:
                lines.append("")
            lines.append(table_name)
            for finding in table_findings:
                wrapped = textwrap.wrap(finding.message, width=self.MESSAGE_WIDTH) or [""]
                first, *rest = wrapped
                lines.append(
                    f"  {finding.severity.value:<7} {finding.code:<14} "
                    f"{(finding.column or '(table)'):<24} {first}"
                )
                for continuation in rest:
                    lines.append(" " * (2 + 7 + 1 + 14 + 1 + 24 + 1) + continuation)

        return "\n".join(lines) + "\n"

    def _summary_line(self, findings: FindingCollection) -> str:
        counts = self._counts(findings)
        total = len(findings)
        noun = "finding" if total == 1 else "findings"
        return (
            f"Joist doctor: {total} {noun} "
            f"({counts['error']} error, {counts['warning']} warning, {counts['info']} info)"
        )

    @staticmethod
    def _counts(findings: FindingCollection) -> dict[str, int]:
        counts = {"error": 0, "warning": 0, "info": 0}
        for finding in findings:
            counts[finding.severity.value] += 1
        return counts


class JsonFormatter:
    """Structured JSON for tooling and CI: every finding with its
    fingerprint, plus a severity summary."""

    def format(self, findings: FindingCollection) -> str:
        summary = {"total": len(findings), "error": 0, "warning": 0, "info": 0}
        payload = {
            "findings": [],
            "summary": summary,
        }
        for finding in findings.all():
            summary[finding.severity.value] += 1
            payload["findings"].append(
                {
                    "code": finding.code,
                    "severity": finding.severity.value,
                    "connection": finding.connection,
                    "table": finding.table,
                    "column": finding.column,
                    "message": finding.message,
                    "hint": finding.hint,
                    "suggestion": finding.suggestion,
                    "fingerprint": finding.fingerprint(),
                }
            )
        return json.dumps(payload, indent=4) + "\n"
