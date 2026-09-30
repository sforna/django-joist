---
name: joist-schema
description: Inspect a Django project's live database schema with Joist when a task depends on actual tables, columns, keys, or relationships.
---

# Joist schema

Use the Joist MCP server to ground database work in the current structure. Start with `list_tables`, then use `describe_table` for specific tables or `focus_table` for a table and its foreign-key neighbours. Use `get_schema` with a compact format only when a wider view is needed.

The tools describe database structure, not row data or business meaning beyond configured annotations. Treat excluded tables and unmanaged connections as unavailable. If the MCP server is unavailable, run `python manage.py joist_export --format=llm` from the Django project root; narrow a large schema with `--focus=<table> --depth=1`.

Report the relevant table and column names you observed, and distinguish live schema facts from inferences about application behavior.
