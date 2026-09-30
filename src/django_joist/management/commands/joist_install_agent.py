"""Install Joist's MCP connection and task skills in a Django project."""

from __future__ import annotations

import json
import re
import sys
from importlib import resources
from pathlib import Path

from django.core.management.base import CommandError

from django_joist.cli import JoistCommand

SKILLS = ("joist-schema", "joist-model-review")
AGENTS_NOTE = """<!-- django-joist agent guidance -->
For tasks about the database schema or model structure, use the installed
Joist skills and the `joist` MCP server to inspect the live structure. Joist exposes
structure only; check application code for behavior and never infer row data from it.
"""


class Command(JoistCommand):
    help = "Install Joist MCP settings and schema skills for Claude Code, Codex, and Cursor."
    requires_system_checks: list[str] = []

    def add_arguments(self, parser):
        parser.add_argument(
            "--agent",
            action="append",
            choices=("claude", "codex", "cursor"),
            help="Configure this agent (repeatable; defaults to all three).",
        )
        parser.add_argument(
            "--project-root",
            default=".",
            help="Django project directory containing manage.py (default: current directory).",
        )
        parser.add_argument(
            "--python",
            default=sys.executable,
            help="Python interpreter the agents should use (default: this interpreter).",
        )

    def handle(self, *args, **options):
        root = Path(options["project_root"]).expanduser().resolve()
        manage_py = root / "manage.py"
        if not manage_py.is_file():
            raise CommandError(f"No manage.py at {manage_py}. Pass --project-root with the Django project directory.")

        agents = set(options["agent"] or ("claude", "codex", "cursor"))
        server = {"command": str(Path(options["python"]).expanduser().resolve()), "args": [str(manage_py), "joist_mcp"]}
        planned: dict[Path, str] = {}

        if "claude" in agents:
            self._plan_json_server(root / ".mcp.json", server, planned)
            self._plan_skills(root / ".claude" / "skills", planned)
        if "codex" in agents:
            self._plan_codex(root / ".codex" / "config.toml", server, planned)
        if "cursor" in agents:
            self._plan_json_server(root / ".cursor" / "mcp.json", server, planned)
        if "codex" in agents or "cursor" in agents:
            self._plan_skills(root / ".agents" / "skills", planned)
        self._plan_agents_note(root / "AGENTS.md", planned)

        for path, content in planned.items():
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            except OSError as exc:
                raise CommandError(f"Could not write {path}: {exc}") from exc
            self.stdout.write(f"Wrote {path.relative_to(root)}")
        if not planned:
            self.stdout.write("Joist agent configuration is already installed.")
        return 0

    @staticmethod
    def _read(path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError) as exc:
            raise CommandError(f"Could not read {path}: {exc}") from exc

    def _plan_json_server(self, path: Path, server: dict, planned: dict[Path, str]) -> None:
        current = self._read(path)
        try:
            config = json.loads(current) if current is not None else {}
        except json.JSONDecodeError as exc:
            raise CommandError(f"Invalid JSON in {path}: {exc}") from exc
        if not isinstance(config, dict) or not isinstance(config.get("mcpServers", {}), dict):
            raise CommandError(f"Expected an object with an mcpServers object in {path}.")
        servers = config.setdefault("mcpServers", {})
        if "joist" in servers:
            if servers["joist"] != server:
                raise CommandError(f"Joist MCP entry in {path} differs; edit it manually before rerunning.")
            return
        servers["joist"] = server
        planned[path] = json.dumps(config, indent=2, ensure_ascii=False) + "\n"

    def _plan_codex(self, path: Path, server: dict, planned: dict[Path, str]) -> None:
        current = self._read(path) or ""
        section = (
            f"[mcp_servers.joist]\ncommand = {json.dumps(server['command'], ensure_ascii=False)}\n"
            f"args = {json.dumps(server['args'], ensure_ascii=False)}\n"
        )
        # Keep unrelated TOML untouched. Detect both dotted and inline Joist
        # declarations before appending, so repeated runs cannot define it twice.
        if re.search(r"(?m)^[ \t]*\[mcp_servers\.(?:joist|\"joist\"|'joist')\][ \t]*(?:#.*)?$", current):
            if section in current:
                return
            raise CommandError(f"Joist MCP entry in {path} differs; edit it manually before rerunning.")
        if re.search(r"(?m)^\s*joist\s*=", current) and re.search(r"(?m)^\s*\[mcp_servers\]\s*$", current):
            raise CommandError(f"Joist MCP entry in {path} differs; edit it manually before rerunning.")
        planned[path] = current.rstrip() + ("\n\n" if current.strip() else "") + section

    def _plan_skills(self, directory: Path, planned: dict[Path, str]) -> None:
        package = resources.files("django_joist")
        for name in SKILLS:
            target = directory / name / "SKILL.md"
            source = package.joinpath("skills").joinpath(name).joinpath("SKILL.md").read_text(encoding="utf-8")
            current = self._read(target)
            if current is None:
                planned[target] = source
            elif current != source:
                raise CommandError(
                    f"Skill at {target} differs from Joist's version; edit it manually before rerunning."
                )

    def _plan_agents_note(self, path: Path, planned: dict[Path, str]) -> None:
        current = self._read(path)
        if current is None:
            planned[path] = "# Project agent guidance\n\n" + AGENTS_NOTE
        elif "<!-- django-joist agent guidance -->" not in current:
            separator = "" if current.endswith("\n\n") else "\n" if current.endswith("\n") else "\n\n"
            planned[path] = current + separator + AGENTS_NOTE
