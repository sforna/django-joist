---
name: joist-model-review
description: Review Django models against the live database structure and Joist's structural findings when asked about model or schema quality.
---

# Joist model review

Read the relevant Django models and use Joist's `describe_table` or `focus_table` to check the corresponding live tables. Run `get_structural_review` for Joist's deterministic findings. If MCP is unavailable, use `python manage.py joist_doctor --format=json` and a focused `joist_export` from the project root.

Compare findings with model definitions and migrations before recommending a change. A structural finding is a clue, not proof of a bug: explain its concrete impact and identify any intentional design or backend behavior that accounts for it. Keep observed schema, Joist findings, and your own recommendations distinct.
