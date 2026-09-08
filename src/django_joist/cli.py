"""Shared CLI plumbing for the ``joist_*`` management commands."""

from __future__ import annotations

from typing import Any, Callable

from django.core.management.base import BaseCommand, CommandError

__all__ = ["JoistCommand", "CommandError"]


class JoistCommand(BaseCommand):
    """A ``BaseCommand`` that treats ``handle()``'s integer return as the process exit code.

    Django discards a command's return value (so the process always exits 0
    unless something raises) and, if the value is truthy, *writes it to
    stdout* - an int there crashes the output wrapper. The reference console
    semantics this package ports are exit-code driven: 0 clean, 1 a real
    finding (a doctor hit at/above ``--fail-on``, an export drift), 2 a usage
    or runtime error.

    This base keeps ``handle`` directly testable as ``assert
    cmd.handle(**opts) == 2`` while, in real CLI runs, raising the
    ``SystemExit`` that makes the process carry that code. The trick is a
    one-shot ``handle`` wrapper during ``execute``: it captures the code,
    returns ``None`` so the parent writes nothing, and the ``SystemExit`` is
    raised after the parent's normal machinery (system checks included) has
    finished.
    """

    def execute(self, *args: Any, **options: Any) -> None:
        captured: dict[str, int | None] = {"code": None}
        original: Callable[..., Any] = self.handle

        def wrapped_handle(*hargs: Any, **hkwargs: Any) -> None:
            result = original(*hargs, **hkwargs)
            captured["code"] = result if isinstance(result, int) else None
            return None  # never let the parent stdout-write our exit code

        self.handle = wrapped_handle  # type: ignore[method-assign]
        try:
            super().execute(*args, **options)
        finally:
            del self.handle  # restore the class-level binding
        if captured["code"]:
            raise SystemExit(captured["code"])
