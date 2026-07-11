import { create } from "zustand";
import type { ApiClient } from "../services/api";
import type {
  AgreementRead,
  ApprovalRead,
  CloneRead,
  EnvironmentInfo,
  HealthResponse,
  MetricsSummary,
  NegotiationRead,
  PeerRead,
} from "../types";

export interface AppState {
  loading: boolean;
  error: string | null;
  health: HealthResponse | null;
  environment: EnvironmentInfo | null;
  clones: CloneRead[];
  peers: PeerRead[];
  negotiations: NegotiationRead[];
  approvals: ApprovalRead[];
  agreements: AgreementRead[];
  metrics: MetricsSummary | null;
  refresh: (client: ApiClient) => Promise<void>;
}

export const useAppStore = create<AppState>((set) => ({
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

  refresh: async (client: ApiClient) => {
    set({ loading: true, error: null });
    try {
      const health = await client.health();
      const environment = await client.getEnvironment();
      const users = await client.listUsers();
      const clones = users.length > 0 ? await client.listClones(users[0].id) : [];
      const [peers, negotiations, approvals, agreements, metrics] = await Promise.all([
        client.listPeers(),
        client.listNegotiations(),
        client.listApprovals(),
        client.listAgreements(),
        client.getMetricsSummary(),
      ]);
      set({
        health,
        environment,
        clones,
        peers,
        negotiations,
        approvals,
        agreements,
        metrics,
        loading: false,
      });
    } catch (error) {
      set({
        loading: false,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  },
}));
