import base64
import hashlib
import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from enishi_core.services import core_discovery
from fastapi.testclient import TestClient


def _mcp_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {core_discovery.mcp_token()}"}


def _external_card(version: str = "enishi-card/1") -> dict[str, object]:
    private_key = Ed25519PrivateKey.generate()
    public_raw = private_key.public_key().public_bytes_raw()
    digest = hashlib.sha256(public_raw).hexdigest()
    card: dict[str, object] = {
        "version": version,
        "agent_id": "agt_" + digest[:16],
        "personal_agent_id": "pa_external",
        "public_key": base64.b64encode(public_raw).decode("ascii"),
        "fingerprint": ":".join(digest[index : index + 2] for index in range(0, 16, 2)),
        "profile": {"display_name": "External Agent"},
        "relay_endpoint": "",
        "issued_at": datetime.now(UTC).isoformat(),
    }
    if version == "enishi-card/2":
        card["capabilities"] = {
            "timezone": "America/Los_Angeles",
            "supported_intents": ["meeting.schedule"],
            "protocol_versions": ["aun/0.2", "aun/0.1"],
        }
    unsigned = json.dumps(
        card, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    card["signature"] = base64.b64encode(private_key.sign(unsigned)).decode("ascii")
    return card


def test_core_json_is_private_and_removed_after_shutdown(
    client: TestClient, tmp_path: Path
) -> None:
    path = tmp_path / "data" / "core.json"
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["pid"] == os.getpid()
    assert len(payload["token"]) >= 32
    assert payload["owner"] == "standalone"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_mcp_token_is_scoped_to_safe_routes(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    assert client.get("/v1/peers", headers=_mcp_headers()).status_code == 200
    assert client.get("/v1/agent/self", headers=_mcp_headers()).status_code == 200
    # 依頼APIには到達できるが、入力不備は通常どおり422になる。
    assert client.post("/v1/agent/requests", headers=_mcp_headers()).status_code == 422
    forbidden = client.get("/v1/users", headers=_mcp_headers())
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "MCP_SCOPE_FORBIDDEN"
    assert client.get("/v1/users", headers=auth_headers).status_code == 200


def test_mcp_can_bootstrap_one_local_agent_only(
    client: TestClient,
) -> None:
    created = client.post(
        "/v1/agent/bootstrap",
        json={"display_name": "中村", "timezone": "Asia/Tokyo", "language": "ja"},
        headers=_mcp_headers(),
    )
    assert created.status_code == 201
    assert created.json()["display_name"] == "中村"
    assert created.json()["active_clone_id"] is None

    status = client.get("/v1/agent/self", headers=_mcp_headers())
    assert status.status_code == 200
    assert status.json()["agents"][0]["user_id"] == created.json()["user_id"]

    duplicate = client.post(
        "/v1/agent/bootstrap",
        json={"display_name": "別ユーザー"},
        headers=_mcp_headers(),
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "LOCAL_AGENT_ALREADY_CONFIGURED"


def test_signed_card_registers_pending_and_tampering_is_rejected(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    first = client.post(
        "/v1/users", json={"display_name": "Alice"}, headers=auth_headers
    ).json()
    card = client.get(
        "/v1/agent/card", params={"user_id": first["id"]}, headers=_mcp_headers()
    )
    assert card.status_code == 200
    assert card.json()["version"] == "enishi-card/2"
    assert card.json()["capabilities"] == {
        "timezone": "Asia/Tokyo",
        "supported_intents": ["meeting.schedule", "task.request"],
        "protocol_versions": ["aun/0.2", "aun/0.1"],
    }

    external_card = _external_card()
    registered = client.post(
        "/v1/peers/from-card", json={"card": external_card}, headers=_mcp_headers()
    )
    assert registered.status_code == 201
    assert registered.json()["status"] == "pending"
    assert registered.json()["capabilities"] == {}

    v2_registered = client.post(
        "/v1/peers/from-card",
        json={"card": _external_card("enishi-card/2")},
        headers=_mcp_headers(),
    )
    assert v2_registered.status_code == 201
    assert v2_registered.json()["capabilities"]["timezone"] == "America/Los_Angeles"

    changed = dict(external_card)
    changed["profile"] = {"display_name": "Mallory"}
    changed["agent_id"] = "agt_tampered"
    rejected = client.post(
        "/v1/peers/from-card", json={"card": changed}, headers=_mcp_headers()
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "IDENTITY_CARD_INVALID"

    self_registration = client.post(
        "/v1/peers/from-card", json={"card": card.json()}, headers=_mcp_headers()
    )
    assert self_registration.status_code == 409
    assert self_registration.json()["error"]["code"] == "SELF_PEER_NOT_ALLOWED"


def test_live_core_discovery_file_cannot_be_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from enishi_core.config import Settings

    settings = Settings(data_dir=tmp_path, cache_dir=tmp_path, log_dir=tmp_path)
    path = tmp_path / "core.json"
    path.write_text(
        json.dumps({"port": 8765, "token": "x" * 32, "pid": 424242}),
        encoding="utf-8",
    )
    path.chmod(0o600)
    monkeypatch.setattr(core_discovery, "_process_alive", lambda _pid: True)
    try:
        core_discovery.publish(settings)
    except RuntimeError as exc:
        assert "既に起動" in str(exc)
    else:
        raise AssertionError("live core.json must not be overwritten")
