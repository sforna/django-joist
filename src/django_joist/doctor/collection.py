"""An immutable list of findings.

The runner is the only place that assembles one; rules just return plain
Finding iterables.
"""

from __future__ import annotations

from typing import Iterable, Iterator

from .finding import Finding


class FindingCollection:
    def __init__(self, findings: Iterable[Finding] = ()) -> None:
        self._findings: list[Finding] = list(findings)

    def sorted(self) -> "FindingCollection":
        """A new collection ordered for reports: most severe first, then
        table name, then rule code, so output is deterministic regardless of
        rule order."""
        ordered = sorted(
            self._findings,
            key=lambda f: (-f.severity.rank, f.table, f.code),
        )
        return FindingCollection(ordered)

    def all(self) -> list[Finding]:
        return list(self._findings)

    def is_empty(self) -> bool:
        return not self._findings

    def __iter__(self) -> Iterator[Finding]:
        return iter(self._findings)

    def __len__(self) -> int:
        return len(self._findings)
