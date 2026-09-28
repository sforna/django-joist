"""joist_mcp: serve the read-only MCP server over stdio.

Launched by an MCP client, not by a person; it speaks newline-delimited
JSON-RPC on stdin/stdout until the client closes the pipe. Five structure-only
tools plus the ``joist://schema`` resource, all over the same cached,
exclusion-filtered snapshot everything else reads. No row data, no writes, no
network. See ``django_joist.mcp`` for the protocol and the safeguards.

Register it with a client as a stdio server, e.g.:

    {
      "mcpServers": {
        "joist": {"command": "python", "args": ["manage.py", "joist_mcp"]}
      }
    }
"""

from __future__ import annotations

from django_joist.cli import JoistCommand


class Command(JoistCommand):
    help = "Serve the read-only, structure-only MCP server over stdio."

    # A protocol stream, not a console: Django's system checks and any banner
    # would land on stdout and corrupt the JSON-RPC framing.
    requires_system_checks: list[str] = []

    def handle(self, *args, **options):
        from django_joist.mcp import run_stdio

        run_stdio()
        return 0
