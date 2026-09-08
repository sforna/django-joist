"""How serious / how sure / which group: the doctor's three vocabularies.

String values are the tokens users type in config and on the CLI
(``--fail-on``, ``--only``), so they are part of the public contract.
"""

from __future__ import annotations

from enum import Enum


class Severity(str, Enum):
    """How serious a finding is. Use :meth:`rank` for order, never declaration
    order - the reference learned that the hard way."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    @property
    def rank(self) -> int:
        return {"error": 3, "warning": 2, "info": 1}[self.value]

    def meets_or_exceeds(self, threshold: "Severity") -> bool:
        return self.rank >= threshold.rank


class Category(str, Enum):
    """The rule groups. The string value is the token for --only/--skip."""

    INTEGRITY = "integrity"
    INDEX = "index"
    TYPE = "type"
    NAMING = "naming"
    FRAMEWORK = "framework"


class Confidence(str, Enum):
    """How sure a rule is that a finding is a real problem, separate from how
    bad it is. The ``recommended`` preset runs High-confidence rules only, so
    heuristic rules stay quiet by default; ``strict`` adds them."""

    HIGH = "high"
    HEURISTIC = "heuristic"
