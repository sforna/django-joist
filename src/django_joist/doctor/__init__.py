"""joist doctor: a deterministic, structure-only review of the schema.

Public API (the contract the HTTP layer and CLI consume)::

    from django_joist.doctor import DoctorReport
    payload = DoctorReport().for_snapshot(alias, snapshot)
"""

from .collection import FindingCollection
from .enums import Category, Confidence, Severity
from .finding import Finding
from .registry import RuleRegistry
from .report import DoctorReport, findings_for
from .runner import DoctorRunner

__all__ = [
    "Category",
    "Confidence",
    "DoctorReport",
    "DoctorRunner",
    "Finding",
    "FindingCollection",
    "RuleRegistry",
    "Severity",
    "findings_for",
]
