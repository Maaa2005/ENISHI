import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../services/api";
import { useNegotiationStore } from "./negotiationStore";

const session = {
  id: "n1",
  initiator_clone_id: "c1",
  responder_clone_id: "c2",
  intent: "meeting.schedule",
  topic: "打ち合わせ",
  status: "agreed",
  session_version: 1,
  result: {},
  created_at: "2026-07-11T12:00:00",
};

const message = {
  protocol: "aun/0.1",
  message_id: "m1",
  session_id: "n1",
  sender_agent_id: "c1",
  receiver_agent_id: "c2",
  message_type: "REQUEST",
  intent: "meeting.schedule",
  session_version: 1,
  payload: {},
  delta: {},
  requires_human_approval: false,
  created_at: "2026-07-11T12:00:00",
};

const metrics = {
  structured: {
    method: "structured",
    input_tokens: 50,
    output_tokens: 50,
    total_tokens: 100,
    llm_calls: 0,
    message_count: 3,
    duration_ms: 0,
  },
  email: {
    method: "email",
    input_tokens: 250,
    output_tokens: 250,
    total_tokens: 500,
    llm_calls: 2,
    message_count: 2,
    duration_ms: 0,
  },
  reduction_rate: 80,
};

const params = {
  initiator_user_id: "u1",
  responder_user_id: "u2",
  topic: "打ち合わせ",
  duration_minutes: 30,
  date_range: { start: "2026-07-13", end: "2026-07-13" },
  preferred_time_ranges: [{ start: "13:00", end: "18:00" }],
};

function makeClient(overrides: Partial<Record<keyof ApiClient, unknown>> = {}): ApiClient {
  return {
    listNegotiations: vi.fn().mockResolvedValue([session]),
    createNegotiation: vi.fn().mockResolvedValue(session),
    listNegotiationMessages: vi.fn().mockResolvedValue([message]),
    getNegotiationMetrics: vi.fn().mockResolvedValue(metrics),
    getNegotiationDecision: vi.fn().mockResolvedValue(null),
    ...overrides,
  } as unknown as ApiClient;
}

describe("negotiationStore", () => {
  beforeEach(() => {
    useNegotiationStore.setState({
      sessions: [],
      selectedSessionId: null,
      messages: [],
      metrics: null,
      decision: null,
      loading: false,
      error: null,
    });
  });

  it("runでcreate→一覧→selectが呼ばれstateが埋まる", async () => {
    const client = makeClient();
    await useNegotiationStore.getState().run(client, params);

    expect(client.createNegotiation).toHaveBeenCalledWith(params);
    expect(client.listNegotiations).toHaveBeenCalled();
    expect(client.listNegotiationMessages).toHaveBeenCalledWith("n1");
    expect(client.getNegotiationMetrics).toHaveBeenCalledWith("n1");

    const state = useNegotiationStore.getState();
    expect(state.sessions).toEqual([session]);
    expect(state.selectedSessionId).toBe("n1");
    expect(state.messages).toEqual([message]);
    expect(state.metrics).toEqual(metrics);
    expect(state.error).toBeNull();
    expect(state.loading).toBe(false);
  });

  it("loadSessionsで一覧を取得する", async () => {
    await useNegotiationStore.getState().loadSessions(makeClient());
    expect(useNegotiationStore.getState().sessions).toEqual([session]);
  });

  it("selectでメッセージとメトリクスを取得する", async () => {
    await useNegotiationStore.getState().select(makeClient(), "n1");
    const state = useNegotiationStore.getState();
    expect(state.selectedSessionId).toBe("n1");
    expect(state.messages).toEqual([message]);
    expect(state.metrics).toEqual(metrics);
  });

  it("失敗時はerrorを設定する", async () => {
    const client = makeClient({
      createNegotiation: vi.fn().mockRejectedValue(new Error("CLONE_REVIEW_REQUIRED")),
    });
    await useNegotiationStore.getState().run(client, params);
    const state = useNegotiationStore.getState();
    expect(state.error).toBe("CLONE_REVIEW_REQUIRED");
    expect(state.loading).toBe(false);
  });
});
