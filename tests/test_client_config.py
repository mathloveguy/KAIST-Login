import json
import sys
import tomllib

import pytest

from kaist_login.cli import parser, perform


@pytest.mark.parametrize("client", ["codex", "claude-desktop", "claude-code"])
def test_generated_client_config(client, capsys):
    perform(parser().parse_args(["mcp-config", "--client", client]))
    output = capsys.readouterr().out
    if client == "codex":
        config = tomllib.loads(output)["mcp_servers"]["kaist_login"]
    else:
        config = json.loads(output)["mcpServers"]["kaist_login"]
        assert config.get("type") == ("stdio" if client == "claude-code" else None)
    assert config["command"] == sys.executable
    assert config["args"] == ["-m", "kaist_login", "serve"]


def test_windows_path_and_spaces_are_json_escaped(monkeypatch, capsys):
    monkeypatch.setattr(sys, "executable", r"C:\Users\Example Name\runtime\python.exe")
    perform(parser().parse_args(["mcp-config", "--client", "claude-desktop"]))
    assert json.loads(capsys.readouterr().out)["mcpServers"]["kaist_login"]["command"] == sys.executable
