"""The optional MCP server for structure-only schema responses.

Exposes the live database structure to a coding agent over the Model Context
Protocol, so the agent queries the current schema on demand instead of being
handed a stale paste. Five tools and one resource, all riding the same cached,
exclusion-filtered snapshot the dashboard, the CLI and the export route read -
no separate introspection, no second source of truth. With the default
settings, every call reads only structure and never touches row data.

The server is deliberately dependency-free: MCP over stdio is newline-
delimited JSON-RPC 2.0, a surface small enough to implement here rather than
pull the official SDK (and its web-server stack) into a host project's
environment. It is opt-in by nature - nothing happens until a client launches
``manage.py joist_mcp`` - so the launch command is the only switch.

Every tool validates the alias against ``managed_aliases()`` and reads through
``ExportBuilder``/``DoctorReport`` so ``excluded_tables`` never reaches the
client, exactly as on the HTTP paths. Transport: one JSON-RPC message per
line on stdin, one response per line on stdout.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any, TextIO

from . import __version__

__all__ = ["RESOURCE_URI", "TOOL_NAMES", "handle_message", "handle_raw", "run_stdio"]

#: Protocol revisions this server speaks. ``initialize`` echoes the client's
#: choice when it is one of these and otherwise answers with the newest, which
#: is how a client learns to downgrade.
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]

RESOURCE_URI = "joist://schema"

INSTRUCTIONS = """\
Joist exposes this Django application's live database structure: tables,
columns, indexes, and foreign keys, plus any annotations the maintainers
declared. Its responses contain structure, not row data, and it never runs a
query you supply. With the default settings, it only reads database metadata.
If the project enabled migration fallback, a connection failure can cause
project migrations to run. Use the schema to ground your work instead of
guessing column and table names.
"""


class JsonRpcError(Exception):
    """An error the protocol layer turns into a JSON-RPC error response."""

    code = -32603

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ToolError(JsonRpcError):
    """A bad argument or unknown tool: invalid-params."""

    code = -32602


class ResourceNotFound(JsonRpcError):
    """An unknown resource URI."""

    code = -32002


# -- shared helpers ----------------------------------------------------------
def _clean(value: Any) -> str | None:
    return str(value) if isinstance(value, str) and value.strip() else None


def _default_format() -> str:
    from .conf import joist_settings

    return str(joist_settings.get("export.default_format", "dbml"))


def _check_format(fmt: str) -> str:
    from .export.exporter import SchemaExporter

    if not SchemaExporter.supports(fmt):
        raise ToolError(
            f"Unknown format [{fmt}]. Supported: {', '.join(SchemaExporter.formats())}."
        )
    return fmt


def _builder(connection: str | None):
    """An ExportBuilder over the cached snapshot, with the managed-alias
    allow-list enforced up front so a typo'd alias reads as such rather than
    as an empty database."""
    from .cache import schema_cache
    from .export.builder import ExportBuilder

    cache = schema_cache()
    try:
        alias = cache.resolve(connection)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    return ExportBuilder(cache=cache).connection(alias)


def _snapshot(connection: str | None) -> dict[str, Any]:
    from .cache import schema_cache

    cache = schema_cache()
    try:
        alias = cache.resolve(connection)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    return cache.get(alias)


# -- tools -------------------------------------------------------------------
def list_tables(arguments: dict[str, Any]) -> str:
    builder = _builder(_clean(arguments.get("connection")))
    try:
        tables = builder.to_array()
    except ValueError:
        # The builder refuses an empty selection; an empty database is not an
        # error here, it is "No tables."
        tables = []
    if not tables:
        return "No tables."

    lines = []
    for table in tables:
        columns = len(table.get("columns") or [])
        has_pk = "has PK" if table.get("primary_key") else "no PK"
        fks = len(table.get("foreign_keys") or [])
        lines.append(
            f"{table['name']}: {columns} columns, {has_pk}, {fks} FK" + ("" if fks == 1 else "s")
        )
    return "\n".join(lines)


def describe_table(arguments: dict[str, Any]) -> str:
    table = _clean(arguments.get("table"))
    if table is None:
        raise ToolError("The `table` argument is required.")
    builder = _builder(_clean(arguments.get("connection")))
    try:
        tables = builder.only([table]).to_array()
    except ValueError as exc:
        # The alias is pre-validated, so an empty selection means the table is
        # unknown or excluded - not a broken request.
        raise ToolError(f"No table [{table}] in this connection's structure.") from exc
    return json.dumps(tables[0])


def get_schema(arguments: dict[str, Any]) -> str:
    fmt = _check_format(_clean(arguments.get("format")) or _default_format())
    builder = _builder(_clean(arguments.get("connection")))
    tables = [t for t in (arguments.get("tables") or []) if isinstance(t, str) and t]
    if tables:
        builder = builder.only(tables)
    if arguments.get("compact"):
        builder = builder.compact()
    try:
        return builder.render(fmt)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


def focus_table(arguments: dict[str, Any]) -> str:
    table = _clean(arguments.get("table"))
    if table is None:
        raise ToolError("The `table` argument is required.")
    fmt = _check_format(_clean(arguments.get("format")) or _default_format())
    depth = arguments.get("depth")
    builder = _builder(_clean(arguments.get("connection")))
    builder = builder.focus(table, int(depth) if depth is not None else None)
    try:
        return builder.render(fmt)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


def get_structural_review(arguments: dict[str, Any]) -> str:
    from .doctor import DoctorReport

    snapshot = _snapshot(_clean(arguments.get("connection")))
    alias = str(snapshot.get("connection") or "default")
    # The doctor re-applies exclusions and its own JOIST['doctor']['exclude'],
    # so the raw snapshot is the right input here - it also carries the
    # ``fallback`` flag the type rules read.
    report = DoctorReport().for_snapshot(alias, snapshot)
    return json.dumps(report)


def _schema_resource() -> str:
    fmt = _default_format()
    return _builder(None).compact().render(fmt)


_RESOURCE_MIME = {"json": "application/json", "csv": "text/csv", "markdown": "text/markdown"}


def _resource_mime() -> str:
    return _RESOURCE_MIME.get(_default_format(), "text/plain")


def _tool_definitions() -> list[dict[str, Any]]:
    from .export.exporter import SchemaExporter

    formats = {
        "type": "string",
        "enum": SchemaExporter.formats(),
        "description": "dbml, json, csv, markdown, mermaid, or llm. Defaults to JOIST['export']['default_format'].",
    }
    connection = {
        "type": "string",
        "description": "The managed connection to read. Defaults to the application default connection.",
    }
    return [
        {
            "name": "list_tables",
            "description": (
                "List the database tables, each with a one-line structural summary: "
                "column count, whether it has a primary key, and foreign-key count. "
                "Structure only, never row data."
            ),
            "inputSchema": {"type": "object", "properties": {"connection": connection}},
            "handler": list_tables,
        },
        {
            "name": "describe_table",
            "description": (
                "Describe one table: its columns (name, type, nullability, default), "
                "primary key, indexes, foreign keys, and any annotations. "
                "Structure only, never row data."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "table": {"type": "string", "description": "The table to describe."},
                    "connection": connection,
                },
                "required": ["table"],
            },
            "handler": describe_table,
        },
        {
            "name": "get_schema",
            "description": (
                "Get the whole database structure in a chosen format (dbml, json, csv, "
                "markdown, mermaid, or llm), optionally compact and limited to specific "
                "tables. Structure only, never row data."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "format": formats,
                    "compact": {
                        "type": "boolean",
                        "description": "Drop defaults and non-unique indexes to shrink the output.",
                    },
                    "tables": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Limit the export to these table names.",
                    },
                    "connection": connection,
                },
            },
            "handler": get_schema,
        },
        {
            "name": "focus_table",
            "description": (
                "Get one table and its foreign-key neighbourhood (out to a given depth) "
                "in a chosen format. Useful for grounding on a slice of the schema. "
                "Structure only, never row data."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "table": {"type": "string", "description": "The table at the centre of the neighbourhood."},
                    "depth": {
                        "type": "integer",
                        "description": (
                            "How many foreign-key hops of neighbours to include. "
                            "Defaults to JOIST['focus']['default_depth']."
                        ),
                    },
                    "format": formats,
                    "connection": connection,
                },
                "required": ["table"],
            },
            "handler": focus_table,
        },
        {
            "name": "get_structural_review",
            "description": (
                "Run the deterministic structural review: problems visible from "
                "structure alone, such as a table with no primary key or an unindexed "
                "foreign key. Returns a severity summary and the findings. "
                "Structure only, no row data."
            ),
            "inputSchema": {"type": "object", "properties": {"connection": connection}},
            "handler": get_structural_review,
        },
    ]


#: The advertised tool names, importable without building the JSON schemas.
TOOL_NAMES = (
    "list_tables",
    "describe_table",
    "get_schema",
    "focus_table",
    "get_structural_review",
)


# -- JSON-RPC method handlers -------------------------------------------------
def _initialize(params: dict[str, Any]) -> dict[str, Any]:
    requested = params.get("protocolVersion")
    version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
    return {
        "protocolVersion": version,
        "capabilities": {
            "tools": {"listChanged": False},
            "resources": {"subscribe": False, "listChanged": False},
        },
        "serverInfo": {"name": "Joist", "version": __version__},
        "instructions": INSTRUCTIONS,
    }


def _list_tools(_params: dict[str, Any]) -> dict[str, Any]:
    return {
        "tools": [
            {"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]}
            for t in _tool_definitions()
        ]
    }


def _call_tool(params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    tool = next((t for t in _tool_definitions() if t["name"] == name), None)
    if tool is None:
        raise ToolError(f"Unknown tool [{name}].")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        raise ToolError("`arguments` must be an object.")

    handler: Callable[[dict[str, Any]], str] = tool["handler"]
    try:
        text = handler(arguments)
    except JsonRpcError as exc:
        # A tool's own failure is a successful call reporting isError, per the
        # MCP contract; only protocol misuse becomes a JSON-RPC error.
        return {"content": [{"type": "text", "text": exc.message}], "isError": True}
    except Exception as exc:  # noqa: BLE001 - never take the server down for one call
        return {"content": [{"type": "text", "text": f"Tool failed: {exc}"}], "isError": True}
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _list_resources(_params: dict[str, Any]) -> dict[str, Any]:
    return {
        "resources": [
            {
                "uri": RESOURCE_URI,
                "name": "Database structure",
                "description": (
                    "The whole database structure (tables, columns, keys, and "
                    "annotations) as one compact, structure-only document."
                ),
                "mimeType": _resource_mime(),
            }
        ]
    }


def _read_resource(params: dict[str, Any]) -> dict[str, Any]:
    uri = params.get("uri")
    if uri != RESOURCE_URI:
        raise ResourceNotFound(f"Unknown resource [{uri}].")
    return {
        "contents": [
            {"uri": RESOURCE_URI, "mimeType": _resource_mime(), "text": _schema_resource()}
        ]
    }


_METHODS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "initialize": _initialize,
    "ping": lambda _params: {},
    "tools/list": _list_tools,
    "tools/call": _call_tool,
    "resources/list": _list_resources,
    "resources/templates/list": lambda _params: {"resourceTemplates": []},
    "resources/read": _read_resource,
    "prompts/list": lambda _params: {"prompts": []},
}


# -- transport ---------------------------------------------------------------
def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def handle_message(message: Any) -> Any:
    """One JSON-RPC message -> one response, a list of responses, or None.

    None means "nothing to say": a notification, which the protocol forbids
    answering. Batches (a JSON array) are supported because JSON-RPC defines
    them, even though MCP clients rarely send one.
    """
    if isinstance(message, list):
        responses = [r for r in (handle_message(m) for m in message) if r is not None]
        return responses or None
    if not isinstance(message, dict) or "method" not in message:
        return _error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid Request")

    msg_id = message.get("id")
    if msg_id is None:
        return None  # notification: initialized, cancelled, progress, ...

    handler = _METHODS.get(str(message["method"]))
    if handler is None:
        return _error(msg_id, -32601, f"Method not found [{message['method']}].")

    params = message.get("params") or {}
    if not isinstance(params, dict):
        return _error(msg_id, -32602, "`params` must be an object.")
    try:
        result = handler(params)
    except JsonRpcError as exc:
        return _error(msg_id, exc.code, exc.message)
    except Exception as exc:  # noqa: BLE001 - a crash in one method is not a crash of the server
        return _error(msg_id, -32603, f"Internal error: {exc}")
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def handle_raw(text: str) -> Any:
    """Parse one transport line and answer it."""
    try:
        message = json.loads(text)
    except json.JSONDecodeError:
        return _error(None, -32700, "Parse error")
    return handle_message(message)


def run_stdio(stdin: TextIO | None = None, stdout: TextIO | None = None) -> None:
    """Serve MCP over stdio until stdin closes: one message per line in, one
    response per line out. Nothing else may touch stdout - a stray print would
    corrupt the stream - and each response is flushed so a client never waits
    on a buffer."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        text = line.strip()
        if not text:
            continue
        response = handle_raw(text)
        if response is None:
            continue
        stdout.write(json.dumps(response) + "\n")
        stdout.flush()
