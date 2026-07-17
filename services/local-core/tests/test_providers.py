from pathlib import Path

from enishi_core.models import CloneContextPackage
from enishi_core.providers.claude_code import build_task_command as build_claude_command
from enishi_core.providers.codex import build_task_command as build_codex_command
from enishi_core.providers.context_file import materialize_context
from fastapi.testclient import TestClient


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


def test_context_file_is_materialized_with_private_permissions_and_removed(tmp_path: Path) -> None:
    package = CloneContextPackage(
        id="ctx1",
        clone_id="clone1",
        clone_version=1,
        task_goal="test",
        relevant_preferences={},
        relevant_skills={},
        relevant_project_context={},
        relevant_decisions=[],
        coding_rules=[],
        prohibited_actions=["secret files"],
        approval_requirements=[],
        file_references=[],
        estimated_tokens=10,
        content_hash="hash",
    )
    with materialize_context(package, tmp_path) as path:
        assert path.exists()
        assert path.stat().st_mode & 0o777 == 0o600
        assert "secret files" in path.read_text(encoding="utf-8")
    assert not path.exists()
