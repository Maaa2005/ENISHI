import { describe, expect, it, vi } from "vitest";
import { ApiClient, EnishiApiError } from "./api";

const connection = { port: 12345, token: "test-token" };

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("ApiClient", () => {
  it("127.0.0.1の指定ポートへBearerトークン付きでリクエストする", async () => {
    const fetchFn = vi.fn().mockResolvedValue(
      jsonResponse({ status: "ok", version: "0.1.0", database_connected: true }),
    );
    const client = new ApiClient(connection, fetchFn);

    const health = await client.health();

    expect(health.status).toBe("ok");
    expect(fetchFn).toHaveBeenCalledWith(
      "http://127.0.0.1:12345/health",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer test-token" }),
      }),
    );
  });

  it("ensureCloneはprovider_typeをボディへ含める", async () => {
    const fetchFn = vi.fn().mockResolvedValue(jsonResponse({ id: "c1", status: "review_required" }));
    const client = new ApiClient(connection, fetchFn);

    await client.ensureClone("u1", "コーディング支援", "codex");

    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:12345/v1/clones/u1/ensure");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      purpose: "コーディング支援",
      provider_type: "codex",
    });
  });

  it("listMemoriesは対象ユーザーをqueryへ含める", async () => {
    const fetchFn = vi.fn().mockResolvedValue(jsonResponse([]));
    const client = new ApiClient(connection, fetchFn);

    await client.listMemories("user 1");

    expect(fetchFn.mock.calls[0][0]).toBe(
      "http://127.0.0.1:12345/v1/memories?user_id=user+1",
    );
  });

  it("listAuditEventsは件数上限をqueryへ含める", async () => {
    const fetchFn = vi.fn().mockResolvedValue(jsonResponse([]));
    const client = new ApiClient(connection, fetchFn);

    await client.listAuditEvents(50);

    expect(fetchFn.mock.calls[0][0]).toBe(
      "http://127.0.0.1:12345/v1/audit-events?limit=50",
    );
  });

  it("プロジェクトとAIタスクを本人に絞って取得する", async () => {
    const fetchFn = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse([])));
    const client = new ApiClient(connection, fetchFn);

    await client.listProjects("user 1");
    await client.listTasks("user 1", 20);

    expect(fetchFn.mock.calls[0][0]).toBe(
      "http://127.0.0.1:12345/v1/projects?user_id=user+1",
    );
    expect(fetchFn.mock.calls[1][0]).toBe(
      "http://127.0.0.1:12345/v1/tasks?limit=20&user_id=user+1",
    );
  });

  it("createTaskはクローンと安全な操作範囲をPOSTする", async () => {
    const fetchFn = vi.fn().mockResolvedValue(jsonResponse({ id: "task1", status: "queued" }));
    const client = new ApiClient(connection, fetchFn);

    await client.createTask({
      user_id: "u1",
      clone_id: "c1",
      project_id: "p1",
      provider: "mock",
      description: "テスト結果を要約する",
      requested_operations: [],
    });

    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:12345/v1/tasks");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      user_id: "u1",
      clone_id: "c1",
      project_id: "p1",
      provider: "mock",
      description: "テスト結果を要約する",
      requested_operations: [],
    });
  });

  it("createNegotiationは/v1/negotiationsへ構造化リクエストをPOSTする", async () => {
    const fetchFn = vi.fn().mockResolvedValue(jsonResponse({ id: "n1", status: "agreed" }));
    const client = new ApiClient(connection, fetchFn);

    const params = {
      initiator_user_id: "u1",
      responder_user_id: "u2",
      topic: "AIエージェントの企画",
      duration_minutes: 30,
      date_range: { start: "2026-07-13", end: "2026-07-17" },
      preferred_time_ranges: [{ start: "13:00", end: "18:00" }],
    };
    await client.createNegotiation(params);

    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:12345/v1/negotiations");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual(params);
  });

  it("getNegotiationMetricsはセッション別メトリクスURLへリクエストする", async () => {
    const fetchFn = vi.fn().mockResolvedValue(
      jsonResponse({
        structured: { method: "structured", total_tokens: 100 },
        email: { method: "email", total_tokens: 500 },
        reduction_rate: 80,
      }),
    );
    const client = new ApiClient(connection, fetchFn);

    await client.getNegotiationMetrics("n1");

    const [url] = fetchFn.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:12345/v1/metrics/negotiations/n1");
  });

  it("putPeerDisclosureは相手別公開設定をPUTする", async () => {
    const fetchFn = vi.fn().mockResolvedValue(jsonResponse({ peer_agent_id: "agt_1" }));
    const client = new ApiClient(connection, fetchFn);

    await client.putPeerDisclosure("agt_1", {
      allowed_memory_types: ["schedule"],
      max_sensitivity: "internal",
      share_schedule: true,
      share_skills: false,
      extra: {},
    });

    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:12345/v1/peers/agt_1/disclosure");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({
      allowed_memory_types: ["schedule"],
      max_sensitivity: "internal",
      share_schedule: true,
      share_skills: false,
      extra: {},
    });
  });

  it("updateUserはプロフィールをPUTする", async () => {
    const fetchFn = vi.fn().mockResolvedValue(jsonResponse({ id: "u1" }));
    const client = new ApiClient(connection, fetchFn);

    await client.updateUser("u1", {
      display_name: "中村奨志",
      nickname: "まさし",
      timezone: "Asia/Tokyo",
      language: "ja",
    });

    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:12345/v1/users/u1");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({
      display_name: "中村奨志",
      nickname: "まさし",
      timezone: "Asia/Tokyo",
      language: "ja",
    });
  });

  it("代理AI設定APIを既定パスへ送る", async () => {
    const fetchFn = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({ rules: {} })));
    const client = new ApiClient(connection, fetchFn);

    await client.putMemorySources([{ source: "github", enabled: true, scope: "repo" }]);
    await client.putDefaultDisclosure({
      allowed_memory_types: ["preference"],
      max_sensitivity: "internal",
      share_schedule: true,
      share_skills: false,
      extra: {},
    });
    await client.putDelegationPolicy("u1", { coding_task: false });
    await client.putApprovalRulesPolicy("u1", { file_delete: true });

    expect(fetchFn.mock.calls[0][0]).toBe("http://127.0.0.1:12345/v1/memory-sources");
    expect(JSON.parse(fetchFn.mock.calls[0][1].body as string)).toEqual({
      sources: [{ source: "github", enabled: true, scope: "repo" }],
    });
    expect(fetchFn.mock.calls[1][0]).toBe("http://127.0.0.1:12345/v1/disclosure/default");
    expect(fetchFn.mock.calls[2][0]).toBe("http://127.0.0.1:12345/v1/policies/delegation");
    expect(fetchFn.mock.calls[3][0]).toBe("http://127.0.0.1:12345/v1/policies/approval-rules");
  });

  it("日程の希望と避けたい時間帯をPUTする", async () => {
    const fetchFn = vi.fn().mockResolvedValue(jsonResponse({ clone_id: "c1", version: 2 }));
    const client = new ApiClient(connection, fetchFn);

    await client.putMeetingPreferences(
      "u1",
      [{ start: "09:00", end: "17:00" }],
      [{ start: "12:00", end: "13:00" }],
    );

    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:12345/v1/users/u1/meeting-preferences");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({
      preferred_time_ranges: [{ start: "09:00", end: "17:00" }],
      avoid_time_ranges: [{ start: "12:00", end: "13:00" }],
    });
  });

  it("承認時に選んだ代替候補を送る", async () => {
    const fetchFn = vi.fn().mockResolvedValue(jsonResponse({ id: "a1", status: "approved" }));
    const client = new ApiClient(connection, fetchFn);
    const selected = { start: "2026-07-20T13:30+09:00", end: "2026-07-20T14:00+09:00" };

    await client.approveApproval("a1", selected);

    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:12345/v1/approvals/a1/approve");
    expect(JSON.parse(init.body as string)).toEqual({ selected_slot: selected });
  });

  it("runMetricsExperimentは条件をPOSTする", async () => {
    const fetchFn = vi.fn().mockResolvedValue(jsonResponse({ id: "experiment_1" }));
    const client = new ApiClient(connection, fetchFn);

    await client.runMetricsExperiment({
      template: "メール文面",
      round_trips: 2,
      uses_delta: true,
    });

    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:12345/v1/metrics/experiments");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      template: "メール文面",
      round_trips: 2,
      uses_delta: true,
    });
  });

  it("エラーレスポンスをEnishiApiErrorへ変換する", async () => {
    const fetchFn = vi.fn().mockImplementation(() =>
      Promise.resolve(
        jsonResponse(
          { error: { code: "LOCAL_CORE_UNAUTHORIZED", message: "トークン不正", details: {} } },
          401,
        ),
      ),
    );
    const client = new ApiClient(connection, fetchFn);

    await expect(client.listUsers()).rejects.toThrowError(EnishiApiError);
    await expect(client.listUsers()).rejects.toMatchObject({
      code: "LOCAL_CORE_UNAUTHORIZED",
    });
  });
});
