import { create } from "zustand";
import type { ApiClient } from "../services/api";
import type {
  AnyNegotiationCreateParams,
  NegotiationMessageRead,
  NegotiationMetrics,
  NegotiationRead,
} from "../types";

export interface NegotiationState {
  sessions: NegotiationRead[];
  selectedSessionId: string | null;
  messages: NegotiationMessageRead[];
  metrics: NegotiationMetrics | null;
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
    set({ loading: true, error: null, selectedSessionId: sessionId });
    try {
      const messages = await client.listNegotiationMessages(sessionId);
      const metrics = await client.getNegotiationMetrics(sessionId);
      set({ messages, metrics, loading: false });
    } catch (error) {
      set({ loading: false, messages: [], metrics: null, error: toErrorMessage(error) });
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
