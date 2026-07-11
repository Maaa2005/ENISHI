import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../services/api";
import { useAppStore } from "./appStore";

const health = { status: "ok", version: "0.1.0", database_connected: true };
const environment = {
  macos_version: "26.5.1",
  architecture: "arm64",
  is_apple_silicon: true,
  python_version: "3.13.13",
  providers: [],
};

function makeClient(overrides: Partial<Record<keyof ApiClient, unknown>> = {}): ApiClient {
  return {
    health: vi.fn().mockResolvedValue(health),
    getEnvironment: vi.fn().mockResolvedValue(environment),
    listUsers: vi.fn().mockResolvedValue([]),
    listClones: vi.fn().mockResolvedValue([]),
    listPeers: vi.fn().mockResolvedValue([]),
    listNegotiations: vi.fn().mockResolvedValue([]),
    listApprovals: vi.fn().mockResolvedValue([]),
    listAgreements: vi.fn().mockResolvedValue([]),
    getMetricsSummary: vi.fn().mockResolvedValue({ methods: [], reduction_rate: null }),
    ...overrides,
  } as unknown as ApiClient;
}

describe("appStore", () => {
  beforeEach(() => {
    useAppStore.setState({
      loading: false,
      error: null,
      health: null,
      environment: null,
      clones: [],
      peers: [],
      negotiations: [],
      approvals: [],
      agreements: [],
      metrics: null,
    });
  });

  it("refreshで状態を取得する", async () => {
    await useAppStore.getState().refresh(makeClient());
    const state = useAppStore.getState();
    expect(state.health).toEqual(health);
    expect(state.environment).toEqual(environment);
    expect(state.error).toBeNull();
    expect(state.loading).toBe(false);
  });

  it("ユーザーが存在すればクローンを取得する", async () => {
    const clones = [{ id: "c1", name: "中村のクローン", status: "review_required" }];
    const client = makeClient({
      listUsers: vi.fn().mockResolvedValue([{ id: "u1" }]),
      listClones: vi.fn().mockResolvedValue(clones),
    });
    await useAppStore.getState().refresh(client);
    expect(useAppStore.getState().clones).toEqual(clones);
  });

  it("接続失敗時はerrorを設定する", async () => {
    const client = makeClient({
      health: vi.fn().mockRejectedValue(new Error("connection refused")),
    });
    await useAppStore.getState().refresh(client);
    const state = useAppStore.getState();
    expect(state.error).toBe("connection refused");
    expect(state.loading).toBe(false);
  });
});
