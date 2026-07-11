from pathlib import Path

from fastapi.testclient import TestClient
from twinlink_core.providers.claude_code import build_task_command as build_claude_command
from twinlink_core.providers.codex import build_task_command as build_codex_command


def test_list_providers_includes_mock(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/v1/providers", headers=auth_headers)
    assert response.status_code == 200
    providers = {item["provider"]: item for item in response.json()}
    assert set(providers) == {"codex", "claude_code", "mock"}
    assert providers["mock"]["installed"] is True
    assert providers["mock"]["authenticated"] is True


def test_detect_provider(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post("/v1/providers/mock/detect", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["version"] == "mock-1.0"


def test_unknown_provider_returns_404(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post("/v1/providers/unknown/detect", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROVIDER_NOT_INSTALLED"


def test_codex_command_is_argument_array() -> None:
    project_root = Path("/tmp/project")
    command = build_codex_command("echo $(rm -rf /)", Path("/tmp/context.json"), project_root)
    assert command[:3] == ["codex", "exec", "--cd"]
    assert str(project_root) in command
    assert "--sandbox" in command
    assert len(command) == 8
    assert all(";" not in part for part in command[:-1])


def test_claude_command_contains_prompt_flag() -> None:
    project_root = Path("/tmp/project")
    command = build_claude_command("修正", Path("/tmp/context.json"), project_root)
    assert command[0] == "claude"
    assert "-p" in command
    assert "--add-dir" in command
    assert str(project_root) in command
