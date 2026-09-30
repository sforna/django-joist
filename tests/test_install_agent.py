"""The installer writes usable project settings and preserves host configuration."""

import hashlib
import json
import os
import sys
from importlib import resources
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from django_joist.management.commands.joist_install_agent import PREVIOUS_SKILL_DIGESTS, SKILLS

PREVIOUS_SKILLS = Path(__file__).parent / "fixtures" / "skills-0.3.0"


def _project(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "manage.py").write_text("# project entry point\n", encoding="utf-8")
    return tmp_path


def test_install_all_agents_and_rerun_without_changes(tmp_path):
    root = _project(tmp_path)
    (root / ".mcp.json").write_text('{"mcpServers":{"other":{"command":"other"}}}', encoding="utf-8")
    (root / ".codex").mkdir()
    (root / ".codex" / "config.toml").write_text('model = "example"\n', encoding="utf-8")
    (root / "AGENTS.md").write_text("# Existing guidance\n", encoding="utf-8")

    call_command("joist_install_agent", project_root=str(root))

    expected = {"command": os.path.abspath(sys.executable), "args": [str(root / "manage.py"), "joist_mcp"]}
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


def _linked_python(tmp_path):
    """A symlink to the running interpreter, the way a virtualenv's ``bin/python`` is laid out."""
    link = tmp_path / "venv" / "bin" / "python"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(sys.executable)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available on this platform")
    return link


def test_interpreter_symlink_is_kept(tmp_path):
    # Resolving a virtualenv's python would start the base interpreter, which
    # cannot import the project's packages.
    root = _project(tmp_path / "project")
    link = _linked_python(tmp_path)
    call_command("joist_install_agent", "--agent", "claude", "--python", str(link), project_root=str(root))
    server = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["joist"]
    assert server["command"] == str(link)


def test_bare_interpreter_name_is_looked_up_on_path(tmp_path, monkeypatch):
    root = _project(tmp_path)
    link = _linked_python(tmp_path)
    monkeypatch.setenv("PATH", str(link.parent))
    call_command("joist_install_agent", "--agent", "claude", "--python", "python", project_root=str(root))
    server = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["joist"]
    assert server["command"] == str(link)

    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with pytest.raises(CommandError, match="not found on PATH"):
        call_command("joist_install_agent", "--agent", "claude", "--python", "python", project_root=str(root))


def test_entry_written_by_0_3_0_is_upgraded(tmp_path):
    # 0.3.0 wrote the resolved interpreter path. That entry is Joist's own
    # output, so a rerun replaces it instead of reporting a conflict.
    root = _project(tmp_path / "project")
    link = _linked_python(tmp_path)
    args = [str(root / "manage.py"), "joist_mcp"]
    old = {"command": str(link.resolve()), "args": args}
    (root / ".mcp.json").write_text(json.dumps({"mcpServers": {"joist": old}}), encoding="utf-8")
    (root / ".codex").mkdir()
    (root / ".codex" / "config.toml").write_text(
        f'model = "example"\n\n[mcp_servers.joist]\n'
        f"command = {json.dumps(old['command'])}\nargs = {json.dumps(args)}\n",
        encoding="utf-8",
    )

    call_command("joist_install_agent", "--agent", "claude", "--agent", "codex", "--python", str(link),
                 project_root=str(root))

    server = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["joist"]
    assert server == {"command": str(link), "args": args}
    codex = (root / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert 'model = "example"' in codex
    assert codex.count("[mcp_servers.joist]") == 1
    assert f"command = {json.dumps(str(link))}" in codex


def test_server_command_after_double_dash_is_used_as_given(tmp_path):
    root = _project(tmp_path)
    command = ["docker", "exec", "-i", "web", "python", "manage.py", "joist_mcp"]
    call_command(
        "joist_install_agent", "--agent", "claude", "--agent", "codex", "--", *command, project_root=str(root)
    )

    server = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["joist"]
    assert server == {"command": "docker", "args": command[1:]}
    codex = (root / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert 'command = "docker"' in codex
    assert json.dumps(command[1:]) in codex

    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    call_command(
        "joist_install_agent", "--agent", "claude", "--agent", "codex", "--", *command, project_root=str(root)
    )
    assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == before


def test_server_command_rejects_python_and_warns_without_joist_mcp(tmp_path, capsys):
    root = _project(tmp_path)
    with pytest.raises(CommandError, match="not both"):
        call_command("joist_install_agent", "--python", sys.executable, "--", "docker", "exec", "-i", "web",
                     project_root=str(root))
    assert not (root / ".mcp.json").exists()

    call_command("joist_install_agent", "--agent", "claude", "--", "docker", "exec", "-i", "web", "python",
                 project_root=str(root))
    assert "does not mention joist_mcp" in capsys.readouterr().err


def test_entry_added_by_claude_mcp_add_is_accepted(tmp_path):
    # `claude mcp add` stores the default transport and an empty environment
    # next to the command; the entry is equivalent, so it is left as it is.
    root = _project(tmp_path)
    command = ["docker", "exec", "-i", "web", "python", "manage.py", "joist_mcp"]
    entry = {"type": "stdio", "command": "docker", "args": command[1:], "env": {}}
    (root / ".mcp.json").write_text(json.dumps({"mcpServers": {"joist": entry}}), encoding="utf-8")
    before = (root / ".mcp.json").read_bytes()

    call_command("joist_install_agent", "--agent", "claude", "--", *command, project_root=str(root))
    assert (root / ".mcp.json").read_bytes() == before

    entry["env"] = {"DJANGO_SETTINGS_MODULE": "other"}
    (root / ".mcp.json").write_text(json.dumps({"mcpServers": {"joist": entry}}), encoding="utf-8")
    with pytest.raises(CommandError, match="differs"):
        call_command("joist_install_agent", "--agent", "claude", "--", *command, project_root=str(root))


def test_skills_from_0_3_0_are_updated_and_customized_skills_are_kept(tmp_path):
    root = _project(tmp_path)
    skills = root / ".claude" / "skills"
    for name in SKILLS:
        (skills / name).mkdir(parents=True)
        (skills / name / "SKILL.md").write_bytes((PREVIOUS_SKILLS / name / "SKILL.md").read_bytes())

    call_command("joist_install_agent", "--agent", "claude", project_root=str(root))

    shipped = resources.files("django_joist") / "skills"
    for name in SKILLS:
        current = (skills / name / "SKILL.md").read_text(encoding="utf-8")
        assert current == (shipped / name / "SKILL.md").read_text(encoding="utf-8")

    (skills / "joist-schema" / "SKILL.md").write_text("# Our own schema notes\n", encoding="utf-8")
    with pytest.raises(CommandError, match=r"Skill at .* differs"):
        call_command("joist_install_agent", "--agent", "claude", project_root=str(root))


def test_previous_skill_digests_match_the_recorded_releases():
    # The digests in the installer must be the ones of the files that were
    # really shipped, and the current skills must not be listed as previous.
    shipped = resources.files("django_joist") / "skills"
    for name in SKILLS:
        old = (PREVIOUS_SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
        assert hashlib.sha256(old.encode("utf-8")).hexdigest() in PREVIOUS_SKILL_DIGESTS[name]
        current = (shipped / name / "SKILL.md").read_text(encoding="utf-8")
        assert hashlib.sha256(current.encode("utf-8")).hexdigest() not in PREVIOUS_SKILL_DIGESTS[name]
