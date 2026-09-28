"""The rule set: fourteen deterministic structural checks.

Grouped by category rather than one file per rule; every class mirrors a
reference rule of the same name and code number (with the JOIST- prefix).
"""

from .indexes import (
    DuplicateIndex,
    ForeignKeyWithoutIndex,
    IndexDuplicatingPrimaryKey,
    MissingUniqueConstraint,
    RedundantPrefixIndex,
    UnindexedSoftDelete,
)
from .integrity import (
    ForeignKeyPointsAtWrongTable,
    ForeignKeyTypeMismatch,
    LikelyMissingForeignKey,
    MissingPrimaryKey,
    PivotWithoutUniqueKey,
    PolymorphicWithoutIndex,
)
from .types import BooleanAsString, MoneyAsFloat

__all__ = [
    "BooleanAsString",
    "DuplicateIndex",
    "ForeignKeyPointsAtWrongTable",
    "ForeignKeyTypeMismatch",
    "ForeignKeyWithoutIndex",
    "IndexDuplicatingPrimaryKey",
    "LikelyMissingForeignKey",
    "MissingPrimaryKey",
    "MissingUniqueConstraint",
    "MoneyAsFloat",
    "PivotWithoutUniqueKey",
    "PolymorphicWithoutIndex",
    "RedundantPrefixIndex",
    "UnindexedSoftDelete",
]
