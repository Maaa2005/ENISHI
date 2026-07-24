import json
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from enishi_core.errors import EnishiError
from enishi_core.security.envelope import build_envelope, canonical_bytes, verify_envelope
from enishi_core.security.keys import ensure_node_keypair
from fastapi.testclient import TestClient


def test_keypair_stable_and_permissions(tmp_path: Path) -> None:
    identity1, _ = ensure_node_keypair(tmp_path)
    identity2, _ = ensure_node_keypair(tmp_path)

    assert identity1.agent_id == identity2.agent_id
    assert identity1.agent_id.startswith("agt_")
    assert identity1.public_key_b64 == identity2.public_key_b64

    key_path = tmp_path / "keys" / "node_ed25519.key"
    assert key_path.exists()
    mode = stat.S_IMODE(key_path.stat().st_mode)
    assert mode == 0o600


def test_keypair_uses_keyring_and_migrates_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import enishi_core.security.keys as keys_module

    monkeypatch.delenv("ENISHI_KEYRING_SERVICE", raising=False)
    original_identity, _ = ensure_node_keypair(tmp_path)
    key_path = tmp_path / "keys" / "node_ed25519.key"
    assert key_path.exists()

    stored: dict[str, str] = {}
    monkeypatch.setenv("ENISHI_KEYRING_SERVICE", "com.enishi.desktop.test")
    monkeypatch.setattr(keys_module, "_keyring_get", lambda service: stored.get(service))
    monkeypatch.setattr(
        keys_module, "_keyring_set", lambda service, value: stored.__setitem__(service, value)
    )

    migrated_identity, _ = ensure_node_keypair(tmp_path)
    reloaded_identity, _ = ensure_node_keypair(tmp_path)

    assert migrated_identity == original_identity
    assert reloaded_identity == original_identity
    assert "com.enishi.desktop.test" in stored
    assert not key_path.exists()


def test_keyring_corruption_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import enishi_core.security.keys as keys_module

    monkeypatch.setenv("ENISHI_KEYRING_SERVICE", "com.enishi.desktop.test")
    monkeypatch.setattr(keys_module, "_keyring_get", lambda _service: "not-base64")

    with pytest.raises(RuntimeError, match="Keychain"):
        ensure_node_keypair(tmp_path)


def _signed_envelope(tmp_path: Path) -> tuple[dict[str, object], str]:
    identity, private_key = ensure_node_keypair(tmp_path)
    envelope = build_envelope(
        sender=identity.agent_id,
        receiver="agt_peer",
        session_id="s001",
        message_type="PROPOSE",
        intent="meeting.schedule",
        session_version=1,
        sequence=2,
        payload={},
        delta={"candidate_slots": [{"start": "2026-07-13T14:00", "end": "2026-07-13T14:30"}]},
        requires_human_approval=False,
        private_key=private_key,
        sender_node_id=identity.agent_id,
        receiver_node_id="agt_peer",
    )
    return envelope, identity.public_key_b64


def test_envelope_sign_and_verify(tmp_path: Path) -> None:
    envelope, public_key = _signed_envelope(tmp_path)
    verify_envelope(envelope, public_key)  # 例外が出なければ成功


def test_jcs_golden_vectors() -> None:
    vectors_path = (
        Path(__file__).parents[3]
        / "packages"
        / "protocol"
        / "test-vectors"
        / "jcs-v0.2.json"
    )
    vectors = json.loads(vectors_path.read_text(encoding="utf-8"))["vectors"]
    for vector in vectors:
        assert canonical_bytes(vector["value"]).decode("utf-8") == vector["canonical_utf8"]


def test_jcs_rejects_non_finite_numbers() -> None:
    import rfc8785

    with pytest.raises(rfc8785.FloatDomainError):
        canonical_bytes({"invalid": float("nan")})


def test_generated_envelope_matches_wire_schema_fields(tmp_path: Path) -> None:
    envelope, _public_key = _signed_envelope(tmp_path)
    schema_path = (
        Path(__file__).parents[3]
        / "packages"
        / "protocol"
        / "schemas"
        / "negotiation-message.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert set(envelope) <= set(schema["properties"])
    assert set(schema["required"]) <= set(envelope)
    import jsonschema

    jsonschema.validate(envelope, schema)


def test_packaged_protocol_schema_matches_public_source() -> None:
    source = (
        Path(__file__).parents[3]
        / "packages"
        / "protocol"
        / "schemas"
        / "negotiation-message.schema.json"
    )
    packaged = (
        Path(__file__).parents[1]
        / "enishi_core"
        / "protocol"
        / "negotiation-message.schema.json"
    )
    assert packaged.read_bytes() == source.read_bytes()


def test_envelope_schema_rejects_wrong_sequence_type(tmp_path: Path) -> None:
    identity, private_key = ensure_node_keypair(tmp_path)
    envelope = build_envelope(
        sender=identity.agent_id,
        receiver="agt_peer",
        session_id="s001",
        message_type="PROPOSE",
        intent="meeting.schedule",
        session_version=1,
        sequence="2",  # type: ignore[arg-type]
        payload={},
        delta={"candidate_slots": []},
        requires_human_approval=False,
        private_key=private_key,
        sender_node_id=identity.agent_id,
        receiver_node_id="agt_peer",
    )
    with pytest.raises(EnishiError) as exc:
        verify_envelope(envelope, identity.public_key_b64)
    assert exc.value.code == "MESSAGE_SCHEMA_INVALID"


def test_envelope_payload_tamper_rejected(tmp_path: Path) -> None:
    envelope, public_key = _signed_envelope(tmp_path)
    envelope["delta"] = {"candidate_slots": []}
    with pytest.raises(EnishiError) as exc:
        verify_envelope(envelope, public_key)
    assert exc.value.code == "MESSAGE_SIGNATURE_INVALID"


def test_envelope_signature_tamper_rejected(tmp_path: Path) -> None:
    envelope, public_key = _signed_envelope(tmp_path)
    envelope["signature"] = "AAAA" + str(envelope["signature"])[4:]
    with pytest.raises(EnishiError) as exc:
        verify_envelope(envelope, public_key)
    assert exc.value.code == "MESSAGE_SIGNATURE_INVALID"


def test_envelope_expired_rejected(tmp_path: Path) -> None:
    envelope, public_key = _signed_envelope(tmp_path)
    future = datetime.now(UTC) + timedelta(seconds=400)
    with pytest.raises(EnishiError) as exc:
        verify_envelope(envelope, public_key, now=future)
    assert exc.value.code == "MESSAGE_EXPIRED"


def test_replay_rejected(client: TestClient) -> None:
    from enishi_core.database import get_session
    from enishi_core.security.replay import check_and_record

    session = next(get_session())
    try:
        check_and_record(session, "msg-001")
        with pytest.raises(EnishiError) as exc:
            check_and_record(session, "msg-001")
        assert exc.value.code == "MESSAGE_REPLAYED"
        assert exc.value.status_code == 409
    finally:
        session.close()


def test_node_identity_endpoint_stable(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    first = client.get("/v1/node/identity", headers=auth_headers)
    second = client.get("/v1/node/identity", headers=auth_headers)
    assert first.status_code == 200
    body = first.json()
    assert body["agent_id"].startswith("agt_")
    assert body["public_key"]
    assert ":" in body["fingerprint"]
    assert second.json() == body
