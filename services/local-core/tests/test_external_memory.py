from pathlib import Path

from fastapi.testclient import TestClient


def test_markdown_folder_connects_and_syncs_idempotently(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    user = client.post(
        "/v1/users", json={"display_name": "Test"}, headers=auth_headers
    ).json()
    vault = tmp_path / "Vault"
    vault.mkdir()
    (vault / "decision.md").write_text("# 採用方針\nローカル優先", encoding="utf-8")

    connected = client.put(
        "/v1/memory-sources",
        json={"sources": [{"source": "obsidian", "enabled": True, "scope": str(vault)}]},
        headers=auth_headers,
    )
    assert connected.status_code == 200
    source = next(item for item in connected.json() if item["source"] == "obsidian")
    assert source["connected"] is True
    assert source["enabled"] is True

    first = client.post(
        "/v1/memory-sources/obsidian/sync",
        json={"user_id": user["id"]},
        headers=auth_headers,
    )
    assert first.status_code == 200
    assert first.json()["created"] == 1

    second = client.post(
        "/v1/memory-sources/obsidian/sync",
        json={"user_id": user["id"]},
        headers=auth_headers,
    )
    assert second.json()["unchanged"] == 1
    memories = client.get(
        "/v1/memories", params={"user_id": user["id"]}, headers=auth_headers
    ).json()
    assert memories[0]["title"] == "採用方針"
    assert memories[0]["sensitivity"] == "private"


def test_missing_markdown_folder_is_not_connected(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    response = client.put(
        "/v1/memory-sources",
        json={
            "sources": [
                {
                    "source": "markdown_folder",
                    "enabled": True,
                    "scope": str(tmp_path / "missing"),
                }
            ]
        },
        headers=auth_headers,
    )
    source = next(item for item in response.json() if item["source"] == "markdown_folder")
    assert source["connected"] is False
    assert source["enabled"] is False
