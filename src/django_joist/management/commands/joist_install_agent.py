"""Install Joist's MCP connection and task skills in a Django project."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
from importlib import resources
from pathlib import Path

from django.core.management.base import CommandError

from django_joist.cli import JoistCommand

SKILLS = ("joist-schema", "joist-model-review")
# SHA-256 of each SKILL.md shipped by earlier releases. A skill with one of
# these digests is Joist's own output, so a rerun updates it instead of
# reporting a customization. When a release changes a skill, add the digest of
# the version it replaces here.
PREVIOUS_SKILL_DIGESTS = {
    "joist-schema": {
        "27f326a1b0b26de91d023836b16ff4049cfa367c601d5d4a012f914e8d19c42b",  # 0.3.0
    },
    "joist-model-review": {
        "8b16932724dc32c02a2019345be7e39f3dc4d8401c602792b71b545d19118624",  # 0.3.0
    },
}
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
            help="Python interpreter the agents should use (default: this interpreter).",
        )
        parser.add_argument(
            "server_command",
            nargs="*",
            metavar="-- COMMAND",
            help=(
                "The full command that starts the Joist MCP server, written after `--` and used as given, "
                "instead of the interpreter and manage.py path. Use it when the agent cannot run the project's "
                "Python directly, e.g. `-- docker exec -i web python manage.py joist_mcp`."
            ),
        )

    def handle(self, *args, **options):
        root = Path(options["project_root"]).expanduser().resolve()
        manage_py = root / "manage.py"
        if not manage_py.is_file():
            raise CommandError(f"No manage.py at {manage_py}. Pass --project-root with the Django project directory.")

        agents = set(options["agent"] or ("claude", "codex", "cursor"))
        # ``legacy`` is the entry 0.3.0 wrote for the same interpreter, with the
        # symlinks resolved. It is Joist's own output, not a customization, so
        # it is replaced instead of reported as a conflict.
        legacy: dict | None = None
        if options["server_command"]:
            if options["python"] is not None:
                raise CommandError("Pass either --python or a server command after `--`, not both.")
            command, *command_args = options["server_command"]
            server = {"command": command, "args": command_args}
            if not any("joist_mcp" in part for part in options["server_command"]):
                self.stderr.write("Warning: the server command does not mention joist_mcp; check that it starts it.")
        else:
            python = self._interpreter(options["python"] or sys.executable)
            server = {"command": python, "args": [str(manage_py), "joist_mcp"]}
            resolved = str(Path(python).resolve())
            if resolved != python:
                legacy = {"command": resolved, "args": server["args"]}
        planned: dict[Path, str] = {}

        if "claude" in agents:
            self._plan_json_server(root / ".mcp.json", server, legacy, planned)
            self._plan_skills(root / ".claude" / "skills", planned)
        if "codex" in agents:
            self._plan_codex(root / ".codex" / "config.toml", server, legacy, planned)
        if "cursor" in agents:
            self._plan_json_server(root / ".cursor" / "mcp.json", server, legacy, planned)
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
    def _interpreter(value: str) -> str:
        """Return an absolute interpreter path without following symlinks.

        A virtualenv's ``python`` is a symlink to the base interpreter;
        resolving it would start Python without the project's packages.
        """
        path = Path(value).expanduser()
        if os.sep not in str(path) and not (os.altsep and os.altsep in str(path)):
            found = shutil.which(str(path))
            if found is None:
                raise CommandError(f"Python interpreter {value!r} was not found on PATH.")
            path = Path(found)
        return os.path.abspath(path)

    @staticmethod
    def _digest(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _read(path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError) as exc:
            raise CommandError(f"Could not read {path}: {exc}") from exc

    def _plan_json_server(self, path: Path, server: dict, legacy: dict | None, planned: dict[Path, str]) -> None:
        current = self._read(path)
        try:
            config = json.loads(current) if current is not None else {}
        except json.JSONDecodeError as exc:
            raise CommandError(f"Invalid JSON in {path}: {exc}") from exc
        if not isinstance(config, dict) or not isinstance(config.get("mcpServers", {}), dict):
            raise CommandError(f"Expected an object with an mcpServers object in {path}.")
        servers = config.setdefault("mcpServers", {})
        if "joist" in servers:
            if self._same_server(servers["joist"], server):
                return
            if not self._same_server(servers["joist"], legacy):
                raise CommandError(f"Joist MCP entry in {path} differs; edit it manually before rerunning.")
        servers["joist"] = server
        planned[path] = json.dumps(config, indent=2, ensure_ascii=False) + "\n"

    @staticmethod
    def _same_server(entry: object, server: dict | None) -> bool:
        # `claude mcp add` also stores the default transport and an empty
        # environment; they launch the same server, so they are not a customization.
        if not isinstance(entry, dict) or server is None:
            return False
        defaults = {"type": "stdio", "env": {}}
        return {key: value for key, value in entry.items() if defaults.get(key, object()) != value} == server

    @staticmethod
    def _codex_section(server: dict) -> str:
        return (
            f"[mcp_servers.joist]\ncommand = {json.dumps(server['command'], ensure_ascii=False)}\n"
            f"args = {json.dumps(server['args'], ensure_ascii=False)}\n"
        )

    def _plan_codex(self, path: Path, server: dict, legacy: dict | None, planned: dict[Path, str]) -> None:
        current = self._read(path) or ""
        section = self._codex_section(server)
        # Keep unrelated TOML untouched. Detect both dotted and inline Joist
        # declarations before appending, so repeated runs cannot define it twice.
        if re.search(r"(?m)^[ \t]*\[mcp_servers\.(?:joist|\"joist\"|'joist')\][ \t]*(?:#.*)?$", current):
            if section in current:
                return
            if legacy is not None and self._codex_section(legacy) in current:
                planned[path] = current.replace(self._codex_section(legacy), section, 1)
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
            if current is None or self._digest(current) in PREVIOUS_SKILL_DIGESTS[name]:
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
