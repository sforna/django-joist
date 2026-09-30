"""The installer writes usable project settings and preserves host configuration."""

import json
import sys
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


def _project(tmp_path):
    (tmp_path / "manage.py").write_text("# project entry point\n", encoding="utf-8")
    return tmp_path


def test_install_all_agents_and_rerun_without_changes(tmp_path):
    root = _project(tmp_path)
    (root / ".mcp.json").write_text('{"mcpServers":{"other":{"command":"other"}}}', encoding="utf-8")
    (root / ".codex").mkdir()
    (root / ".codex" / "config.toml").write_text('model = "example"\n', encoding="utf-8")
    (root / "AGENTS.md").write_text("# Existing guidance\n", encoding="utf-8")

    call_command("joist_install_agent", project_root=str(root))

    expected = {"command": str(Path(sys.executable).resolve()), "args": [str(root / "manage.py"), "joist_mcp"]}
    claude = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))
    cursor = json.loads((root / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert claude["mcpServers"] == {"other": {"command": "other"}, "joist": expected}
    assert cursor["mcpServers"]["joist"] == expected

    codex = (root / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert 'model = "example"' in codex
    assert "[mcp_servers.joist]" in codex
    assert str(root / "manage.py") in codex

    note = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "# Existing guidance" in note
    assert note.count("<!-- django-joist agent guidance -->") == 1
    for name in ("joist-schema", "joist-model-review"):
        assert (root / ".claude" / "skills" / name / "SKILL.md").is_file()
        assert (root / ".agents" / "skills" / name / "SKILL.md").is_file()

    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    call_command("joist_install_agent", project_root=str(root))
    assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == before


def test_selected_agent_only_and_conflict_has_no_partial_write(tmp_path):
    root = _project(tmp_path)
    call_command("joist_install_agent", "--agent", "cursor", project_root=str(root))
    assert (root / ".cursor" / "mcp.json").exists()
    assert (root / ".agents" / "skills" / "joist-schema" / "SKILL.md").exists()
    assert not (root / ".mcp.json").exists()
    assert not (root / ".codex").exists()

    (root / ".cursor" / "mcp.json").write_text('{"mcpServers":{"joist":{"command":"custom"}}}', encoding="utf-8")
    with pytest.raises(CommandError, match="differs"):
        call_command("joist_install_agent", project_root=str(root))
    assert not (root / ".mcp.json").exists()
    assert not (root / ".codex").exists()


def test_requires_project_root_with_manage_py(tmp_path):
    with pytest.raises(CommandError, match=r"No manage\.py"):
        call_command("joist_install_agent", project_root=str(tmp_path))
