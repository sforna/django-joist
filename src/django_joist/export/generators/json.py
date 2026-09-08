"""The whole selection as a JSON array of tables, in the exact serializer shape.

Structure only. Global notes are not added: that would reshape the top level
away from a plain table array, and the bare-array shape is what consumers
(tooling, tests, diffing) rely on. Per-table/per-column annotations ride
along as the ``annotation`` keys the Annotator already attached, so an
un-annotated snapshot encodes identically.

No volatile data: no connection name, no timestamp. Two runs on the same
schema are byte-identical, which is what makes ``--check`` meaningful.
"""

from __future__ import annotations

import json
from typing import Any


class JsonGenerator:
    def generate(self, tables: list[dict[str, Any]], notes: list[str] | None = None) -> str:
        # indent=2 and ensure_ascii=False mirror the reference's pretty,
        # slash- and unicode-preserving output; insertion order (the wire
        # field order) is preserved because the snapshot is built as ordered
        # dicts end to end.
        return json.dumps(tables, indent=2, ensure_ascii=False)
