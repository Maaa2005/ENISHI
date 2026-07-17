import { create } from "zustand";
import { EnishiApiError, type ApiClient } from "../services/api";
import type {
  AgentIdentityRead,
  AgreementRead,
  ApprovalRead,
  CloneRead,
  EnvironmentInfo,
  HealthResponse,
  MetricsSummary,
  NegotiationRead,
  PeerRead,
  RelayStatusRead,
  UserRead,
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
  users: UserRead[];
  agentIdentity: AgentIdentityRead | null;
  relayStatus: RelayStatusRead | null;
  requesting: boolean;
  requestError: string | null;
  requestCandidates: Array<{ agent_id: string; display_name: string }>;
  refresh: (client: ApiClient) => Promise<void>;
  submitAgentRequest: (client: ApiClient, userId: string, text: string, peerAgentId?: string) => Promise<boolean>;
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
  users: [],
  agentIdentity: null,
  relayStatus: null,
  requesting: false,
  requestError: null,
  requestCandidates: [],

  submitAgentRequest: async (client, userId, text, peerAgentId) => {
    set({ requesting: true, requestError: null, requestCandidates: [] });
    try {
      const negotiation = await client.createAgentRequest({
        user_id: userId,
        text,
        ...(peerAgentId ? { peer_agent_id: peerAgentId } : {}),
      });
      set((state) => ({
        requesting: false,
        negotiations: [negotiation, ...state.negotiations.filter((n) => n.id !== negotiation.id)],
      }));
      return true;
    } catch (error) {
      const candidates = error instanceof EnishiApiError && Array.isArray(error.details.candidates)
        ? error.details.candidates.filter(
          (item): item is { agent_id: string; display_name: string } =>
            typeof item === "object" && item !== null &&
            typeof (item as Record<string, unknown>).agent_id === "string" &&
            typeof (item as Record<string, unknown>).display_name === "string",
        )
        : [];
      set({
        requesting: false,
        requestError: error instanceof Error ? error.message : String(error),
        requestCandidates: candidates,
      });
      return false;
    }
  },

  refresh: async (client: ApiClient) => {
    set({ loading: true, error: null });
    try {
      const health = await client.health();
      const environment = await client.getEnvironment();
      const users = await client.listUsers();
      const clones = users.length > 0 ? await client.listClones(users[0].id) : [];
      const agentIdentity = users.length > 0 ? await client.getAgentIdentity(users[0].id) : null;
      const [peers, negotiations, approvals, agreements, metrics, relayStatus] = await Promise.all([
        client.listPeers(),
        client.listNegotiations(),
        client.listApprovals(),
        client.listAgreements(),
        client.getMetricsSummary(),
        client.getRelayStatus(),
      ]);
      set({
        health,
        environment,
        users,
        agentIdentity,
        clones,
        peers,
        negotiations,
        approvals,
        agreements,
        metrics,
        relayStatus,
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
