"""The rule contract: a single structural check, pure over the snapshot.

A rule receives a serialized snapshot (the shape SchemaSerializer produces)
plus the connection name, and yields Findings. It never reads config,
suppressions, or output; severity overrides, ignore patterns, and ordering
are the runner's job.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from ..enums import Category, Confidence, Severity
from ..finding import Finding


class Rule(ABC):
    #: Stable machine identifier, e.g. "JOIST-IDX-001". Permanent once shipped.
    code: str
    category: Category
    confidence: Confidence
    default_severity: Severity
    #: One line, shown in reports.
    title: str

    @abstractmethod
    def check(self, snapshot: dict, connection: str) -> Iterable[Finding]:
        """Yield a Finding per structural problem visible in the snapshot."""
        raise NotImplementedError


def pluralize(word: str) -> str:
    """The tiny slice of Laravel's ``Str::plural`` the name-matching heuristics
    need. Deliberately naive: these are guesses in heuristic rules, and a
    miss costs a skipped finding, never a false one worth an English library."""
    if not word:
        return word
    if word.endswith("y") and len(word) > 1 and word[-2] not in "aeiou":
        return word[:-1] + "ies"
    if word.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    return word + "s"


def table_columns(table: dict) -> list[str]:
    return [c["name"] for c in table.get("columns", [])]


def column_type(table: dict, name: str) -> str | None:
    for column in table.get("columns", []):
        if column["name"] == name:
            return column.get("type")
    return None
