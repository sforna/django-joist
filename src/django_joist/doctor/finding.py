"""One structural problem a rule found."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from typing import Optional

from .enums import Severity


@dataclass(frozen=True)
class Finding:
    """Structure only: it names the table and (optionally) column, never any
    row data.

    ``message`` says what is wrong, ``hint`` says why it matters,
    ``suggestion`` is an optional migration snippet or None.
    """

    code: str  # e.g. "JOIST-IDX-001"
    severity: Severity
    connection: str
    table: str
    column: Optional[str]  # or an index / constraint name, or None
    message: str
    hint: str
    suggestion: Optional[str] = None

    def fingerprint(self) -> str:
        """A stable identity for suppression. Built from code, connection,
        table, and column only, so re-wording a message never invalidates a
        suppression, and it does not depend on production order.

        The hex-sha256 format is shared with the reference so a mixed
        Laravel/Django estate can dedupe findings client-side."""
        raw = "|".join([self.code, self.connection, self.table, self.column or ""])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def with_severity(self, severity: Severity) -> "Finding":
        """A copy at a different severity, for the runner's per-rule
        overrides. Every other field, and therefore the fingerprint, is
        unchanged."""
        return replace(self, severity=severity)
