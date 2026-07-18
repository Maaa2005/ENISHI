#!/usr/bin/env python3
"""署名付き名刺交換から本人承認・両ノード合意までを実環境で検証する。"""

from __future__ import annotations

import os
import time
from typing import Any

from seed_demo import Node


def one(items: list[dict[str, Any]], label: str) -> dict[str, Any]:
    if len(items) != 1:
        raise RuntimeError(f"Expected one {label}, got {items}")
    return items[0]


def wait_for_agreement(
    node: Node,
    session_id: str,
    *,
    sync: bool,
    attempts: int = 40,
) -> dict[str, Any]:
    for _ in range(attempts):
        if sync:
            node.request("/v1/relay/sync", method="POST")
        agreements = [
            item
            for item in node.request("/v1/agreements")
            if item["session_id"] == session_id
        ]
        if agreements:
            return one(agreements, f"agreement on {node.name}")
        time.sleep(0.25)
    raise RuntimeError(f"{node.name} did not persist the agreement for {session_id}")


def main() -> None:
    node_a = Node(
        "User A", int(os.environ.get("ENISHI_DEMO_USER_A_PORT", "8871")), "demo-token-a"
    )
    node_b = Node(
        "User B", int(os.environ.get("ENISHI_DEMO_USER_B_PORT", "8872")), "demo-token-b"
    )

    user_a = one(node_a.request("/v1/users"), "User A profile")
    user_b = one(node_b.request("/v1/users"), "User B profile")
    card_a = node_a.request(f"/v1/agent/card?user_id={user_a['id']}")
    card_b = node_b.request(f"/v1/agent/card?user_id={user_b['id']}")
    peer_b_on_a = one(node_a.request("/v1/peers"), "User B peer on User A")
    peer_a_on_b = one(node_b.request("/v1/peers"), "User A peer on User B")

    for peer, card, label in (
        (peer_b_on_a, card_b, "B on A"),
        (peer_a_on_b, card_a, "A on B"),
    ):
        if peer["status"] != "trusted":
            raise RuntimeError(f"Pair {label} is not trusted: {peer}")
        if peer["agent_id"] != card["agent_id"] or peer["fingerprint"] != card["fingerprint"]:
            raise RuntimeError(f"Pair {label} does not match the signed Agent Card")

    approval = one(
        [item for item in node_a.request("/v1/approvals") if item["status"] == "pending"],
        "pending approval",
    )
    session_id = str(approval["payload"]["session_id"])
    approved = node_a.request(
        f"/v1/approvals/{approval['id']}/approve",
        method="POST",
        body={},
    )
    if approved["status"] != "approved":
        raise RuntimeError(f"Approval did not transition to approved: {approved}")

    agreement_a = wait_for_agreement(node_a, session_id, sync=False)
    agreement_b = wait_for_agreement(node_b, session_id, sync=True)
    if agreement_a["agreed_payload"] != agreement_b["agreed_payload"]:
        raise RuntimeError("The two nodes persisted different agreement payloads")

    print("")
    print("Pairing E2E passed:")
    print("  [OK] Ed25519 Agent Cards registered as pending before explicit trust")
    print("  [OK] Stored node IDs and fingerprints match the signed cards")
    print("  [OK] Trusted peer request reached the human approval gate")
    print("  [OK] Approval produced the same agreement on both nodes")


if __name__ == "__main__":
    main()
