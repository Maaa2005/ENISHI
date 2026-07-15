import { create } from "zustand";
import type { ApiClient } from "../services/api";
import type {
  AnyNegotiationCreateParams,
  NegotiationDecisionRead,
  NegotiationMessageRead,
  NegotiationMetrics,
  NegotiationRead,
} from "../types";

export interface NegotiationState {
  sessions: NegotiationRead[];
  selectedSessionId: string | null;
  messages: NegotiationMessageRead[];
  metrics: NegotiationMetrics | null;
  decision: NegotiationDecisionRead | null;
  loading: boolean;
  error: string | null;
  loadSessions: (client: ApiClient) => Promise<void>;
  select: (client: ApiClient, sessionId: string) => Promise<void>;
  run: (client: ApiClient, params: AnyNegotiationCreateParams) => Promise<void>;
}

function toErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export const useNegotiationStore = create<NegotiationState>((set, get) => ({
  sessions: [],
  selectedSessionId: null,
  messages: [],
  metrics: null,
  decision: null,
  loading: false,
  error: null,

  loadSessions: async (client: ApiClient) => {
    set({ loading: true, error: null });
    try {
      const sessions = await client.listNegotiations();
      set({ sessions, loading: false });
    } catch (error) {
      set({ loading: false, error: toErrorMessage(error) });
    }
  },

  select: async (client: ApiClient, sessionId: string) => {
    set({ loading: true, error: null, selectedSessionId: sessionId, messages: [], metrics: null, decision: null });
    try {
      const [messages, metrics, decision] = await Promise.all([
        client.listNegotiationMessages(sessionId),
        client.getNegotiationMetrics(sessionId),
        client.getNegotiationDecision(sessionId),
      ]);
      set({ messages, metrics, decision, loading: false });
    } catch (error) {
      set({ loading: false, messages: [], metrics: null, decision: null, error: toErrorMessage(error) });
    }
  },

  run: async (client: ApiClient, params: AnyNegotiationCreateParams) => {
    set({ loading: true, error: null });
    try {
      const created = await client.createNegotiation(params);
      await get().loadSessions(client);
      await get().select(client, created.id);
    } catch (error) {
      set({ loading: false, error: toErrorMessage(error) });
    }
  },
}));
