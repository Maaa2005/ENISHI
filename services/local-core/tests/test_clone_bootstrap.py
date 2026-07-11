from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient


def _create_user(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post("/v1/users", json={"display_name": "中村"}, headers=headers)
    assert response.status_code == 201
    return response.json()["id"]


def _add_memory(
    client: TestClient,
    headers: dict[str, str],
    user_id: str,
    *,
    memory_type: str = "preference",
    title: str = "コーヒーが好き",
    content: dict[str, object] | None = None,
    sensitivity: str = "internal",
    confidence: float = 0.5,
) -> str:
    response = client.post(
        "/v1/memories",
        json={
            "user_id": user_id,
            "source_type": "manual",
            "memory_type": memory_type,
            "title": title,
            "content": content or {"detail": "test"},
            "sensitivity": sensitivity,
            "confidence": confidence,
        },
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()["id"]


def _build_draft(user_id: str, project_id: str | None = None) -> dict[str, object]:
    from twinlink_core.database import get_session
    from twinlink_core.services.clone_bootstrap import build_clone_draft

    session = next(get_session())
    try:
        clone = build_clone_draft(
            session,
            user_id=user_id,
            purpose="コーディング支援",
            provider_type="mock",
            project_id=project_id,
        )
        return {
            "id": clone.id,
            "version": clone.version,
            "preference_profile": clone.preference_profile,
            "skill_profile": clone.skill_profile,
            "project_profile": clone.project_profile,
            "communication_profile": clone.communication_profile,
            "coding_profile": clone.coding_profile,
            "policy_profile": clone.policy_profile,
            "confidence_score": clone.confidence_score,
            "memory_snapshot_id": clone.memory_snapshot_id,
            "status": clone.status,
        }
    finally:
        session.close()


def test_profiles_built_from_memories(client: TestClient, auth_headers: dict[str, str]) -> None:
    user_id = _create_user(client, auth_headers)
    _add_memory(client, auth_headers, user_id, memory_type="preference", title="好み")
    _add_memory(client, auth_headers, user_id, memory_type="skill", title="Python")
    _add_memory(client, auth_headers, user_id, memory_type="communication", title="敬語")
    _add_memory(client, auth_headers, user_id, memory_type="decision", title="型必須")
    _add_memory(client, auth_headers, user_id, memory_type="environment", title="macOS")

    draft = _build_draft(user_id)
    assert draft["status"] == "review_required"
    assert "好み" in draft["preference_profile"]
    assert "Python" in draft["skill_profile"]
    assert "敬語" in draft["communication_profile"]
    assert "型必須" in draft["policy_profile"]["decisions"]
    assert "macOS" in draft["coding_profile"]["environment"]
    assert draft["confidence_score"] == 0.3 + 0.05 * 5


def test_duplicate_memory_highest_confidence_wins(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    user_id = _create_user(client, auth_headers)
    content = {"detail": "同一内容"}
    _add_memory(
        client, auth_headers, user_id, title="重複", content=content, confidence=0.2
    )
    _add_memory(
        client, auth_headers, user_id, title="重複", content=content, confidence=0.9
    )

    from twinlink_core.database import get_session
    from twinlink_core.services.clone_bootstrap import _deduplicate
    from twinlink_core.services.memories import exportable_memories

    session = next(get_session())
    try:
        selected, conflicts = _deduplicate(exportable_memories(session, user_id))
    finally:
        session.close()
    assert conflicts == 0
    assert len(selected) == 1
    assert selected[0].confidence == 0.9


def test_conflicting_memory_latest_updated_wins(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    user_id = _create_user(client, auth_headers)
    old_id = _add_memory(
        client, auth_headers, user_id, title="矛盾", content={"answer": "古い"}
    )
    new_id = _add_memory(
        client, auth_headers, user_id, title="矛盾", content={"answer": "新しい"}
    )

    # updated_at を明示的にずらして決定的にする
    from twinlink_core.database import get_session
    from twinlink_core.models import MemoryItem

    session = next(get_session())
    try:
        old = session.get(MemoryItem, old_id)
        new = session.get(MemoryItem, new_id)
        assert old is not None and new is not None
        old.updated_at = datetime(2026, 1, 1, tzinfo=UTC)
        new.updated_at = datetime(2026, 6, 1, tzinfo=UTC)
        session.commit()
    finally:
        session.close()

    draft = _build_draft(user_id)
    assert draft["preference_profile"]["矛盾"] == {"answer": "新しい"}
    assert draft["policy_profile"]["conflicts"] == 1


def test_secret_memory_excluded_from_all_profiles(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    user_id = _create_user(client, auth_headers)
    _add_memory(
        client,
        auth_headers,
        user_id,
        memory_type="preference",
        title="極秘の好み",
        sensitivity="secret",
    )
    _add_memory(
        client,
        auth_headers,
        user_id,
        memory_type="skill",
        title="極秘スキル",
        sensitivity="secret",
    )

    draft = _build_draft(user_id)
    profiles = (
        draft["preference_profile"],
        draft["skill_profile"],
        draft["project_profile"],
        draft["communication_profile"],
        draft["coding_profile"],
        draft["policy_profile"],
    )
    for profile in profiles:
        assert "極秘の好み" not in str(profile)
        assert "極秘スキル" not in str(profile)


def test_collect_project_signals(tmp_path: Path) -> None:
    from twinlink_core.services.memory_sources import collect_project_signals

    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["fastapi", "sqlalchemy"]\n', encoding="utf-8"
    )
    (tmp_path / "README.md").write_text("# Demo\nデモプロジェクト", encoding="utf-8")

    signals = collect_project_signals(tmp_path)
    assert signals["languages"] == ["Python"]
    assert "fastapi" in signals["frameworks"]
    assert signals["readme_summary"].startswith("# Demo")
    assert set(signals["detected_files"]) == {"README.md", "pyproject.toml"}


def test_collect_project_signals_skips_symlink_escape(tmp_path: Path) -> None:
    from twinlink_core.services.memory_sources import collect_project_signals

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("外部の秘密", encoding="utf-8")

    root = tmp_path / "project"
    root.mkdir()
    (root / "README.md").symlink_to(outside / "secret.md")

    signals = collect_project_signals(root)
    assert signals["detected_files"] == []
    assert signals["readme_summary"] == ""


def test_rebuild_increments_version_and_outdates_old(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    user_id = _create_user(client, auth_headers)
    clone = client.post(
        f"/v1/clones/{user_id}/ensure",
        json={"purpose": "コーディング支援", "provider_type": "mock"},
        headers=auth_headers,
    ).json()

    rebuilt = client.post(f"/v1/clones/{clone['id']}/rebuild", headers=auth_headers)
    assert rebuilt.status_code == 200
    assert rebuilt.json()["version"] == clone["version"] + 1
    assert rebuilt.json()["status"] == "review_required"

    listed = client.get(f"/v1/clones/{user_id}", headers=auth_headers).json()
    statuses = {c["id"]: c["status"] for c in listed}
    assert statuses[clone["id"]] == "outdated"


def test_ensure_clone_reflects_memories_via_api(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    user_id = _create_user(client, auth_headers)
    _add_memory(client, auth_headers, user_id, memory_type="preference", title="簡潔な回答")

    clone = client.post(
        f"/v1/clones/{user_id}/ensure",
        json={"purpose": "コーディング支援", "provider_type": "mock"},
        headers=auth_headers,
    ).json()

    assert clone["status"] == "review_required"
    assert clone["coding_profile"]["approval_rules"]["git_push"] is False

    listed = client.get(f"/v1/clones/{user_id}", headers=auth_headers).json()
    assert len(listed) == 1

    from twinlink_core.database import get_session
    from twinlink_core.models import CloneAgent

    session = next(get_session())
    try:
        stored = session.get(CloneAgent, clone["id"])
        assert stored is not None
        assert "簡潔な回答" in stored.preference_profile
    finally:
        session.close()
