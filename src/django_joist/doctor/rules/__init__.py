"""The rule set: fourteen deterministic structural checks.

Grouped by category rather than one file per rule; every class mirrors a
reference rule of the same name and code number (with the JOIST- prefix).
"""

from .integrity import (
    ForeignKeyPointsAtWrongTable,
    ForeignKeyTypeMismatch,
    LikelyMissingForeignKey,
    MissingPrimaryKey,
    PivotWithoutUniqueKey,
    PolymorphicWithoutIndex,
)
from .types import BooleanAsString, MoneyAsFloat
from .indexes import (
    DuplicateIndex,
    ForeignKeyWithoutIndex,
    IndexDuplicatingPrimaryKey,
    MissingUniqueConstraint,
    RedundantPrefixIndex,
    UnindexedSoftDelete,
)

__all__ = [
    "MissingPrimaryKey",
    "LikelyMissingForeignKey",
    "ForeignKeyTypeMismatch",
    "PivotWithoutUniqueKey",
    "PolymorphicWithoutIndex",
    "ForeignKeyPointsAtWrongTable",
    "ForeignKeyWithoutIndex",
    "DuplicateIndex",
    "RedundantPrefixIndex",
    "IndexDuplicatingPrimaryKey",
    "UnindexedSoftDelete",
    "MissingUniqueConstraint",
    "MoneyAsFloat",
    "BooleanAsString",
]
