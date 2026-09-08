"""Type rules (JOIST-TYP-*): columns whose storage type contradicts their
name. Both are name-based heuristics and stay quiet on the recommended
preset; types are the native full strings the snapshot carries."""

from __future__ import annotations

from typing import Iterable

from ..enums import Category, Confidence, Severity
from ..finding import Finding
from .base import Rule


class MoneyAsFloat(Rule):
    """JOIST-TYP-001: a money-looking column stored as float/double/real.
    Binary floating point cannot represent decimal money exactly, so totals
    drift. The money-ness is inferred from the name, so a non-money float (a
    ratio, a weight) is not flagged."""

    code = "JOIST-TYP-001"
    category = Category.TYPE
    confidence = Confidence.HEURISTIC
    default_severity = Severity.ERROR
    title = "Money-looking column stored as float"

    MONEY_TERMS = ["price", "cost", "amount", "total", "balance", "salary", "fee", "tax", "discount"]

    def check(self, snapshot: dict, connection: str) -> Iterable[Finding]:
        for table in snapshot.get("tables", []):
            for column in table.get("columns", []):
                if not self._is_floating_point(column.get("type", "")):
                    continue
                if not self._looks_like_money(column.get("name", "")):
                    continue
                yield Finding(
                    code=self.code,
                    severity=self.default_severity,
                    connection=connection,
                    table=table["name"],
                    column=column["name"],
                    message=(
                        f"Column \"{table['name']}.{column['name']}\" holds "
                        f"money-looking values as {column['type']}, which cannot "
                        "represent money exactly."
                    ),
                    hint=(
                        "Store money as DecimalField, or as an integer number of "
                        "cents. FloatField introduces rounding errors that corrupt "
                        "totals. Ignore this if the column is not actually money."
                    ),
                )

    @staticmethod
    def _is_floating_point(type_name: str) -> bool:
        lowered = str(type_name).lower()
        return any(word in lowered for word in ("float", "double", "real"))

    @classmethod
    def _looks_like_money(cls, name: str) -> bool:
        lowered = name.lower()
        return any(term in lowered for term in cls.MONEY_TERMS)


class BooleanAsString(Rule):
    """JOIST-TYP-002: an ``is_*`` or ``has_*`` column, which reads as a yes/no
    flag, stored as a character or text type. A column that genuinely holds
    more than two values can be ignored."""

    code = "JOIST-TYP-002"
    category = Category.TYPE
    confidence = Confidence.HEURISTIC
    default_severity = Severity.WARNING
    title = "Boolean-looking column stored as text"

    def check(self, snapshot: dict, connection: str) -> Iterable[Finding]:
        for table in snapshot.get("tables", []):
            for column in table.get("columns", []):
                name = str(column.get("name", "")).lower()
                if not (name.startswith("is_") or name.startswith("has_")):
                    continue
                ctype = str(column.get("type", "")).lower()
                if "char" not in ctype and "text" not in ctype:
                    continue
                yield Finding(
                    code=self.code,
                    severity=self.default_severity,
                    connection=connection,
                    table=table["name"],
                    column=column["name"],
                    message=(
                        f"Column \"{table['name']}.{column['name']}\" reads as a "
                        f"yes/no flag but is stored as {column['type']}."
                    ),
                    hint=(
                        "A boolean-looking column is clearer and smaller as a "
                        "BooleanField. Ignore this if it genuinely holds more than "
                        "two values."
                    ),
                )
