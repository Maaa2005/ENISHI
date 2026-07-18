#!/usr/bin/env python3
"""Seed a fresh two-person ENISHI presentation and leave one approval pending."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Any


class Node:
    def __init__(self, name: str, port: int, token: str) -> None:
        self.name = name
        self.base_url = f"http://127.0.0.1:{port}"
        self.token = token

    def request(
        self, path: str, *, method: str = "GET", body: dict[str, Any] | None = None
    ) -> Any:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=payload,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{self.name} {method} {path}: HTTP {exc.code} {detail}") from exc


def create_user(node: Node, display_name: str) -> dict[str, Any]:
    return node.request(
        "/v1/users", method="POST", body={"display_name": display_name, "nickname": display_name}
    )


def add_memory(
    node: Node,
    user_id: str,
    memory_type: str,
    title: str,
    content: dict[str, Any],
) -> None:
    node.request(
        "/v1/memories",
        method="POST",
        body={
            "user_id": user_id,
            "source_type": "presentation_demo",
            "memory_type": memory_type,
            "title": title,
            "content": content,
            "confidence": 0.95,
            "sensitivity": "internal",
            "relevance_tags": ["demo"],
        },
    )


def seed_profile(
    node: Node,
    user_id: str,
    peer_personal_agent_id: str,
    *,
    require_approval: bool,
) -> None:
    memories = [
        (
            "preference",
            "meeting_schedule",
            {
                "preferred_time_ranges": [{"start": "13:00", "end": "18:00"}],
                "avoid_time_ranges": [],
            },
        ),
        (
            "preference",
            "relationships",
            {peer_personal_agent_id: {"allow_auto_accept": not require_approval}},
        ),
        ("communication", "response_style", {"language": "ja", "tone": "concise"}),
        ("identity", "role", {"value": "student"}),
        ("skill", "coordination", {"level": "comfortable"}),
        ("policy", "privacy", {"share_raw_calendar": False}),
        ("environment", "timezone", {"value": "Asia/Tokyo"}),
    ]
    for memory_type, title, content in memories:
        add_memory(node, user_id, memory_type, title, content)


def activate_clone(node: Node, user_id: str) -> dict[str, Any]:
    clone = node.request(
        f"/v1/clones/{user_id}/ensure",
        method="POST",
        body={"purpose": "日程調整", "provider_type": "mock"},
    )
    return node.request(f"/v1/clones/{clone['id']}/activate", method="POST")


def connect_from_card(
    node: Node,
    peer_card: dict[str, Any],
) -> dict[str, Any]:
    peer = node.request(
        "/v1/peers/from-card",
        method="POST",
        body={"card": peer_card},
    )
    if peer["status"] != "pending":
        raise RuntimeError(f"{node.name} accepted an Agent Card without a pending gate: {peer}")
    if peer["fingerprint"] != peer_card["fingerprint"]:
        raise RuntimeError(f"{node.name} stored a fingerprint that differs from the signed card")
    trusted = node.request(f"/v1/peers/{peer['agent_id']}/trust", method="POST")
    if trusted["status"] != "trusted":
        raise RuntimeError(f"{node.name} did not establish trust after explicit confirmation")
    node.request(
        f"/v1/peers/{peer['agent_id']}/disclosure",
        method="PUT",
        body={
            "allowed_memory_types": ["schedule", "preference"],
            "max_sensitivity": "internal",
            "share_schedule": True,
            "share_skills": False,
            "extra": {},
        },
    )
    return trusted


def wait_for_pending_approval(node: Node, attempts: int = 30) -> dict[str, Any]:
    for _ in range(attempts):
        node.request("/v1/relay/sync", method="POST")
        approvals = node.request("/v1/approvals")
        pending = [item for item in approvals if item["status"] == "pending"]
        if pending:
            return pending[0]
        time.sleep(0.25)
    raise RuntimeError("The seeded negotiation did not reach the approval screen.")


def seed_project_task(
    node: Node,
    user_id: str,
    clone_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    repository_root = Path(__file__).resolve().parents[1]
    project = node.request(
        "/v1/projects",
        method="POST",
        body={
            "user_id": user_id,
            "name": "ENISHI",
            "root_path": str(repository_root),
        },
    )
    project = node.request(
        f"/v1/projects/{project['id']}",
        method="PATCH",
        body={"trusted": True},
    )
    task = node.request(
        "/v1/tasks",
        method="POST",
        body={
            "user_id": user_id,
            "clone_id": clone_id,
            "project_id": project["id"],
            "provider": "mock",
            "description": "ENISHIのテスト結果とデモ準備状況を要約する",
            "requested_operations": [],
        },
    )
    for _ in range(30):
        task = node.request(f"/v1/tasks/{task['id']}")
        if task["status"] in {"completed", "failed"}:
            break
        time.sleep(0.1)
    if task["status"] != "completed":
        raise RuntimeError("The seeded coding task did not complete.")
    return project, task


def main() -> None:
    user_a_node = Node(
        "User A", int(os.environ.get("ENISHI_DEMO_USER_A_PORT", "8871")), "demo-token-a"
    )
    user_b_node = Node(
        "User B", int(os.environ.get("ENISHI_DEMO_USER_B_PORT", "8872")), "demo-token-b"
    )

    user_a = create_user(user_a_node, "中村 奨志")
    user_b = create_user(user_b_node, "水野先生")
    identity_a = user_a_node.request(f"/v1/agent/identity?user_id={user_a['id']}")
    identity_b = user_b_node.request(f"/v1/agent/identity?user_id={user_b['id']}")
    card_a = user_a_node.request(f"/v1/agent/card?user_id={user_a['id']}")
    card_b = user_b_node.request(f"/v1/agent/card?user_id={user_b['id']}")

    seed_profile(
        user_a_node,
        user_a["id"],
        identity_b["personal_agent_id"],
        require_approval=True,
    )
    seed_profile(
        user_b_node,
        user_b["id"],
        identity_a["personal_agent_id"],
        require_approval=False,
    )
    clone_a = activate_clone(user_a_node, user_a["id"])
    activate_clone(user_b_node, user_b["id"])
    project, task = seed_project_task(user_a_node, user_a["id"], clone_a["id"])

    connect_from_card(user_a_node, card_b)
    connect_from_card(user_b_node, card_a)
    for node, user in ((user_a_node, user_a), (user_b_node, user_b)):
        node.request(
            "/v1/policies/delegation",
            method="PUT",
            body={"user_id": user["id"], "rules": {"schedule_negotiation": True}},
        )

    meeting_date = (date.today() + timedelta(days=3)).isoformat()
    request_text = (
        f"{meeting_date}に30分、13:00〜17:00で卒業制作ENISHIの進捗相談"
    )
    negotiation = user_b_node.request(
        "/v1/agent/requests",
        method="POST",
        body={
            "user_id": user_b["id"],
            "peer_agent_id": identity_a["node_id"],
            "text": request_text,
        },
    )
    approval = wait_for_pending_approval(user_a_node)

    print("")
    print("Presentation data is ready.")
    print("  Scenario: 水野先生の代理AI -> 中村さんの代理AI")
    print(f"  Request:  {request_text}")
    print(f"  Session:  {negotiation['id']}")
    print(f"  Approval: {approval['id']} (pending on User A)")
    print("  Pairing:  signed Agent Card -> pending -> fingerprint check -> trusted")
    print(f"  Project:  {project['name']} (trusted, restricted permissions)")
    print(f"  AI task:  {task['id']} (completed with mock provider)")
    print("  Privacy:  raw calendar and private memory are not sent")


if __name__ == "__main__":
    main()
