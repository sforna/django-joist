"""The payload the dashboard runs on, assembled in one place.

There is one producer of this shape on purpose: ``views.schema_api`` serves it
over HTTP and ``django_joist.payload()`` returns it in process, and both call
:func:`dashboard_payload`, so a custom page never has to make an HTTP request
to its own site and can never receive a second, subtly different assembly.

Invariants owned here:

* ``excluded_tables`` (global + per-connection) are filtered out of the cached
  snapshot at serve time, before the diff and the doctor run, so an excluded
  table cannot surface through either of them.
* ``diff`` is null or an object; ``diff_unavailable`` is set beside it only
  when the baseline could not be read (never for "no baseline yet").
* ``cache_unavailable`` is set only when the snapshot had to be built live.
  The structure is complete either way.

No authorization runs here: that belongs to whatever exposes the result.
Structure only, never row contents.
"""

from __future__ import annotations

from typing import Any

from .cache import schema_cache
from .conf import joist_settings
from .selection import without_excluded_tables


def dashboard_payload(alias: str | None = None) -> dict[str, Any]:
    """The dashboard payload for a managed alias (the first managed one when
    None). Raises ``ValueError`` for an alias Joist does not manage: the HTTP
    route turns that into a 404, an in-process caller gets the error rather
    than an empty payload that would hide a programming mistake."""
    cache = schema_cache()
    alias = cache.resolve(alias)

    # A copy, so a caller mutating the result cannot reach a snapshot the
    # cache backend handed out by reference (locmem returns fresh objects,
    # a custom backend need not).
    snapshot = dict(cache.get(alias))
    # A snapshot Joist could not cache is still a correct snapshot, just built
    # live. Flagged rather than raising: the diagram works on a broken cache
    # store and the caller can say why.
    cache_unavailable = cache.last_error is not None

    snapshot["tables"] = without_excluded_tables(snapshot.get("tables", []), alias)
    diff_result, baseline_unavailable = _diff_for(alias, snapshot)
    snapshot["diff"] = diff_result
    snapshot["doctor"] = _doctor_for(alias, snapshot)
    if baseline_unavailable:
        snapshot["diff_unavailable"] = True
    if cache_unavailable:
        snapshot["cache_unavailable"] = True
    return snapshot


def _diff_for(alias: str, snapshot: dict) -> tuple[Any, bool]:
    """The structural diff against the recorded baseline, or None when the
    feature is off or no baseline exists. The baseline is filtered through the
    same exclusion list before comparison, so an excluded table never
    surfaces via the diff either."""
    if not joist_settings.get("diff.enabled", True):
        return None, False

    from .diff.baseline import BaselineStore
    from .diff.differ import SchemaDiffer

    baselines = BaselineStore()
    baseline = baselines.get(alias)
    if baseline is None:
        # A read failure and "no baseline yet" both land here; only the first
        # is worth telling anyone about (the second is a fresh install's
        # normal state until the next migration).
        return None, baselines.last_error is not None

    baseline["tables"] = without_excluded_tables(baseline.get("tables", []), alias)
    return SchemaDiffer().diff(baseline, snapshot), False


def _doctor_for(alias: str, snapshot: dict) -> dict | None:
    """The doctor report, or None when the dashboard Health panel is off. The
    snapshot is already exclusion-filtered, so excluded tables never reach a
    finding."""
    if not joist_settings.get("doctor.dashboard", True):
        return None

    from .doctor import DoctorReport

    return DoctorReport().for_snapshot(alias, snapshot)
