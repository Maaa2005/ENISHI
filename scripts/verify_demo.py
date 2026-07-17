#!/usr/bin/env python3
"""発表UIを出す前に、承認フローとLocal Core接続を自己診断する。"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any


def request_json(port: int, path: str, token: str | None = None) -> Any:
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers)
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


def verify_cors(core_port: int, ui_port: int) -> None:
    origin = f"http://127.0.0.1:{ui_port}"
    request = urllib.request.Request(
        f"http://127.0.0.1:{core_port}/v1/approvals",
        method="OPTIONS",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        allowed_origin = response.headers.get("Access-Control-Allow-Origin")
    if allowed_origin != origin:
        raise RuntimeError(f"Demo UI origin is not allowed by Local Core: {allowed_origin!r}")


def main() -> None:
    user_a_port = int(os.environ["ENISHI_DEMO_USER_A_PORT"])
    user_b_port = int(os.environ["ENISHI_DEMO_USER_B_PORT"])
    ui_port = int(os.environ["ENISHI_DEMO_UI_PORT"])
    token_a = "demo-token-a"

    for name, port in (("User A", user_a_port), ("User B", user_b_port)):
        health = request_json(port, "/health")
        if health.get("status") != "ok" or not health.get("database_connected"):
            raise RuntimeError(f"{name} Local Core is not ready: {health}")

    users = request_json(user_a_port, "/v1/users", token_a)
    if len(users) != 1 or users[0].get("display_name") != "中村 奨志":
        raise RuntimeError(f"Presenter profile is not ready: {users}")
    user_id = users[0]["id"]

    approvals = request_json(user_a_port, "/v1/approvals", token_a)
    pending = [item for item in approvals if item.get("status") == "pending"]
    if len(pending) != 1 or pending[0].get("action_type") != "negotiation_decision":
        raise RuntimeError(f"Expected one pending negotiation approval: {approvals}")

    projects = request_json(user_a_port, f"/v1/projects?user_id={user_id}", token_a)
    if len(projects) != 1 or projects[0].get("name") != "ENISHI":
        raise RuntimeError(f"Demo project is not ready: {projects}")

    tasks = request_json(user_a_port, f"/v1/tasks?user_id={user_id}", token_a)
    if len(tasks) != 1 or tasks[0].get("status") != "completed":
        raise RuntimeError(f"Demo AI task is not complete: {tasks}")

    verify_cors(user_a_port, ui_port)
    print("")
    print("Demo self-check passed:")
    print("  [OK] User A/B Local Core and database")
    print("  [OK] Local authentication and presenter profile (中村 奨志)")
    print("  [OK] One pending negotiation approval")
    print("  [OK] Restricted ENISHI project and completed AI task")
    print("  [OK] Demo UI CORS origin")


if __name__ == "__main__":
    main()
