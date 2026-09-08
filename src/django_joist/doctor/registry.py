"""Holds the available rules and resolves the active set for a run.

Selection is kept out of the runner: given a preset, category filters, and
per-rule enable/disable, this returns the rules to run. Severity overrides
and ignore patterns are the runner's job, not the registry's.
"""

from __future__ import annotations

from typing import Iterable

from .enums import Confidence
from .rules import (
    BooleanAsString,
    DuplicateIndex,
    ForeignKeyPointsAtWrongTable,
    ForeignKeyTypeMismatch,
    ForeignKeyWithoutIndex,
    IndexDuplicatingPrimaryKey,
    LikelyMissingForeignKey,
    MissingPrimaryKey,
    MissingUniqueConstraint,
    MoneyAsFloat,
    PivotWithoutUniqueKey,
    PolymorphicWithoutIndex,
    RedundantPrefixIndex,
    UnindexedSoftDelete,
)
from .rules.base import Rule


class RuleRegistry:
    def __init__(self, *rules: Rule) -> None:
        self._rules = list(rules)

    @classmethod
    def default(cls) -> "RuleRegistry":
        """The shipped rule set, in code order."""
        return cls(
            MissingPrimaryKey(),
            LikelyMissingForeignKey(),
            ForeignKeyTypeMismatch(),
            PivotWithoutUniqueKey(),
            PolymorphicWithoutIndex(),
            ForeignKeyPointsAtWrongTable(),
            ForeignKeyWithoutIndex(),
            DuplicateIndex(),
            RedundantPrefixIndex(),
            IndexDuplicatingPrimaryKey(),
            UnindexedSoftDelete(),
            MissingUniqueConstraint(),
            MoneyAsFloat(),
            BooleanAsString(),
        )

    def all(self) -> list[Rule]:
        return list(self._rules)

    def resolve(
        self,
        preset: str = "recommended",
        only: Iterable[str] = (),
        skip: Iterable[str] = (),
        enabled: dict[str, bool] | None = None,
    ) -> list[Rule]:
        """The rules to run.

        The preset picks a baseline ("recommended" runs high-confidence rules
        only, "strict" runs everything, "none" runs nothing), an explicit
        enable/disable per code overrides that baseline (so a heuristic rule
        can be switched on, or a rule switched off), and only/skip narrow by
        category last.
        """
        enabled = enabled or {}
        only = list(only)
        skip = list(skip)
        return [
            rule
            for rule in self._rules
            if self._is_active(rule, preset, enabled) and self._passes_category_filters(rule, only, skip)
        ]

    @staticmethod
    def _is_active(rule: Rule, preset: str, enabled: dict[str, bool]) -> bool:
        if rule.code in enabled:
            return enabled[rule.code]
        if preset == "strict":
            return True
        if preset == "recommended":
            return rule.confidence is Confidence.HIGH
        return False

    @staticmethod
    def _passes_category_filters(rule: Rule, only: list[str], skip: list[str]) -> bool:
        category = rule.category.value
        if only and category not in only:
            return False
        return category not in skip
