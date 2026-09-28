"""The optional MCP server: protocol framing and the five tools.

Two layers. The protocol tests drive ``handle_message`` as pure JSON-RPC (no
database, no client library): handshake, notifications, tool listing, errors.
The tool tests go through the real snapshot and the real doctor, so what they
pin is that every call rides the same exclusion-filtered services as the
dashboard - an excluded table must not appear in a listing or a description.
Finally one test pushes newline-delimited messages through the management
command itself, which is the framing a client actually sees.
"""

import io
import json

import pytest
from django.core.management import call_command

from django_joist import mcp
from django_joist.cache import schema_cache

pytestmark = pytest.mark.django_db(databases=["default", "secondary"])


# -- helpers -----------------------------------------------------------------
def _request(method, params=None, id=1):
    message = {"jsonrpc": "2.0", "id": id, "method": method}
    if params is not None:
        message["params"] = params
    return mcp.handle_message(message)


def _call(name, **arguments):
    reply = _request("tools/call", {"name": name, "arguments": arguments})
    assert "result" in reply, reply
    return reply["result"]


def _text(result):
    assert result["isError"] is False, result
    return result["content"][0]["text"]


def _error_text(result):
    assert result["isError"] is True, result
    return result["content"][0]["text"]


def _visible(alias="default"):
    from django_joist.selection import without_excluded_tables

    snapshot = schema_cache().get(alias)
    return without_excluded_tables(snapshot["tables"], snapshot["connection"])


# -- protocol ----------------------------------------------------------------
def test_initialize_echoes_a_supported_protocol_version():
    result = _request("initialize", {"protocolVersion": "2024-11-05"})["result"]
    assert result["protocolVersion"] == "2024-11-05"
    assert result["serverInfo"]["name"] == "Joist"
    assert result["instructions"]


def test_initialize_falls_back_to_the_newest_for_an_unknown_version():
    result = _request("initialize", {"protocolVersion": "1999-01-01"})["result"]
    assert result["protocolVersion"] == mcp.LATEST_PROTOCOL_VERSION


def test_initialize_advertises_tools_and_resources():
    capabilities = _request("initialize", {})["result"]["capabilities"]
    assert capabilities["tools"]["listChanged"] is False
    assert capabilities["resources"]["subscribe"] is False


def test_a_notification_gets_no_reply():
    assert mcp.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_unknown_method_is_a_jsonrpc_error():
    reply = _request("does/not/exist")
    assert reply["error"]["code"] == -32601


def test_a_batch_keeps_only_the_requests_that_need_an_answer():
    replies = mcp.handle_message(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
        ]
    )
    assert len(replies) == 1 and replies[0]["id"] == 1


def test_unparsable_input_is_a_parse_error():
    reply = mcp.handle_raw("{not json")
    assert reply["error"]["code"] == -32700


def test_a_tools_list_advertises_every_tool_with_a_schema():
    tools = _request("tools/list")["result"]["tools"]
    assert [t["name"] for t in tools] == list(mcp.TOOL_NAMES)
    for tool in tools:
        assert tool["description"] and tool["inputSchema"]["type"] == "object"


# -- tools -------------------------------------------------------------------
def test_list_tables_reports_the_visible_tables(snapshot):
    text = _text(_call("list_tables"))
    names = [line.split(":", 1)[0] for line in text.splitlines()]
    assert names == [t["name"] for t in _visible()]
    assert "django_migrations" not in text  # excluded by default


def test_list_tables_summarises_each_table(snapshot):
    text = _text(_call("list_tables"))
    book = next(t for t in _visible() if t["name"] == "testapp_book")
    line = next(l for l in text.splitlines() if l.startswith("testapp_book:"))
    assert line == (
        f"testapp_book: {len(book['columns'])} columns, has PK, "
        f"{len(book['foreign_keys'])} FKs"
    )


def test_list_tables_says_no_tables_when_everything_is_excluded(snapshot, settings_overrides):
    settings_overrides("excluded_tables", [t["name"] for t in snapshot["tables"]])
    assert _text(_call("list_tables")) == "No tables."


def test_list_tables_rejects_an_unmanaged_connection():
    assert "not managed" in _error_text(_call("list_tables", connection="secondary"))


def test_describe_table_returns_the_structure(snapshot):
    table = json.loads(_text(_call("describe_table", table="testapp_book")))
    assert table["name"] == "testapp_book"
    assert table["primary_key"] == ["id"]
    assert {c["name"] for c in table["columns"]} >= {"id", "title", "author_id"}
    assert len(table["foreign_keys"]) == 2


def test_describe_table_reports_an_unknown_table():
    assert "No table [testapp_nope]" in _error_text(_call("describe_table", table="testapp_nope"))


def test_describe_table_requires_the_table_argument():
    assert "required" in _error_text(_call("describe_table"))


def test_describe_table_respects_exclusions(snapshot, settings_overrides):
    settings_overrides("excluded_tables", ["testapp_book"])
    assert "No table [testapp_book]" in _error_text(_call("describe_table", table="testapp_book"))


def test_get_schema_renders_the_default_format(snapshot):
    text = _text(_call("get_schema"))
    assert "testapp_book" in text  # DBML by default


def test_get_schema_honours_format_and_tables(snapshot):
    payload = json.loads(_text(_call("get_schema", format="json", tables=["testapp_author"])))
    assert [t["name"] for t in payload] == ["testapp_author"]


def test_get_schema_rejects_an_unknown_format(snapshot):
    assert "Unknown format [yaml]" in _error_text(_call("get_schema", format="yaml"))


def test_focus_table_returns_the_neighbourhood(snapshot):
    text = _text(_call("focus_table", table="testapp_book", depth=1, format="json"))
    names = {t["name"] for t in json.loads(text)}
    assert "testapp_book" in names
    assert "testapp_author" in names  # neighbour by foreign key


def test_focus_table_reports_a_missing_root(snapshot):
    assert "no such table" in _error_text(_call("focus_table", table="testapp_nope")).lower()


def test_get_structural_review_returns_a_summary_and_findings(snapshot):
    report = json.loads(_text(_call("get_structural_review")))
    assert report["summary"]["total"] >= 1  # the test app carries deliberate bait
    assert all("code" in f and "severity" in f for f in report["findings"])


def test_resources_list_advertises_the_schema_resource():
    resources = _request("resources/list")["result"]["resources"]
    assert [r["uri"] for r in resources] == [mcp.RESOURCE_URI]


def test_resources_read_returns_the_compact_structure(snapshot):
    result = _request("resources/read", {"uri": mcp.RESOURCE_URI})["result"]
    assert result["contents"][0]["uri"] == mcp.RESOURCE_URI
    assert "testapp_book" in result["contents"][0]["text"]


def test_resources_read_rejects_an_unknown_uri():
    reply = _request("resources/read", {"uri": "joist://nope"})
    assert reply["error"]["code"] == -32002


# -- the command's stdio framing ---------------------------------------------
def test_the_command_speaks_one_json_message_per_line(snapshot, monkeypatch):
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "list_tables", "arguments": {}}},
    ]
    stdin = io.StringIO("\n".join(json.dumps(m) for m in messages) + "\n")
    stdout = io.StringIO()
    monkeypatch.setattr("sys.stdin", stdin)
    monkeypatch.setattr("sys.stdout", stdout)

    call_command("joist_mcp")

    lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
    # Exactly two replies - the notification produced none - and no banner.
    assert [line["id"] for line in lines] == [1, 2]
    assert "testapp_book" in lines[1]["result"]["content"][0]["text"]
