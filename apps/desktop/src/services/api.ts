import type {
  AgreementRead,
  AgentIdentityRead,
  AgentRequestCreateParams,
  AnyNegotiationCreateParams,
  ApprovalRead,
  CloneRead,
  CoreConnection,
  DefaultDisclosurePolicyRead,
  EnvironmentInfo,
  HealthResponse,
  MemorySourceSettingPatch,
  MemorySourceSettingRead,
  MetricsSummary,
  MetricsExperimentRead,
  NegotiationMessageRead,
  NegotiationDecisionRead,
  NegotiationMetrics,
  NegotiationRead,
  NodeIdentityRead,
  PeerCreateParams,
  PeerDisclosurePolicyRead,
  PeerRead,
  PolicyRead,
  ProviderStatusDetail,
  RelayStatusRead,
  UserRead,
  UserUpdateParams,
} from "../types";

export class EnishiApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "EnishiApiError";
  }
}

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export class ApiClient {
  constructor(
    private readonly connection: CoreConnection,
    private readonly fetchFn: FetchLike = (input, init) => fetch(input, init),
  ) {}

  private get baseUrl(): string {
    // Local Coreは127.0.0.1限定で待ち受ける（enishi.md §10）
    return `http://127.0.0.1:${this.connection.port}`;
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await this.fetchFn(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${this.connection.token}`,
        ...init?.headers,
      },
    });
    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as {
        error?: { code?: string; message?: string; details?: Record<string, unknown> };
      } | null;
      throw new EnishiApiError(
        body?.error?.code ?? "UNKNOWN_ERROR",
        body?.error?.message ?? `HTTP ${response.status}`,
        body?.error?.details ?? {},
      );
    }
    return (await response.json()) as T;
  }

  health(): Promise<HealthResponse> {
    return this.request<HealthResponse>("/health");
  }

  getEnvironment(): Promise<EnvironmentInfo> {
    return this.request<EnvironmentInfo>("/v1/system/environment");
  }

  listUsers(): Promise<UserRead[]> {
    return this.request<UserRead[]>("/v1/users");
  }

  createUser(displayName: string): Promise<UserRead> {
    return this.request<UserRead>("/v1/users", {
      method: "POST",
      body: JSON.stringify({ display_name: displayName }),
    });
  }

  updateUser(userId: string, params: UserUpdateParams): Promise<UserRead> {
    return this.request<UserRead>(`/v1/users/${encodeURIComponent(userId)}`, {
      method: "PUT",
      body: JSON.stringify(params),
    });
  }

  listMemorySources(): Promise<MemorySourceSettingRead[]> {
    return this.request<MemorySourceSettingRead[]>("/v1/memory-sources");
  }

  putMemorySources(sources: MemorySourceSettingPatch[]): Promise<MemorySourceSettingRead[]> {
    return this.request<MemorySourceSettingRead[]>("/v1/memory-sources", {
      method: "PUT",
      body: JSON.stringify({ sources }),
    });
  }

  getDefaultDisclosure(): Promise<DefaultDisclosurePolicyRead> {
    return this.request<DefaultDisclosurePolicyRead>("/v1/disclosure/default");
  }

  putDefaultDisclosure(
    policy: Omit<DefaultDisclosurePolicyRead, "created_at" | "updated_at">,
  ): Promise<DefaultDisclosurePolicyRead> {
    return this.request<DefaultDisclosurePolicyRead>("/v1/disclosure/default", {
      method: "PUT",
      body: JSON.stringify(policy),
    });
  }

  getDelegationPolicy(userId: string): Promise<PolicyRead> {
    return this.request<PolicyRead>(
      `/v1/policies/delegation?${new URLSearchParams({ user_id: userId }).toString()}`,
    );
  }

  putDelegationPolicy(userId: string, rules: Record<string, boolean>): Promise<PolicyRead> {
    return this.request<PolicyRead>("/v1/policies/delegation", {
      method: "PUT",
      body: JSON.stringify({ user_id: userId, rules }),
    });
  }

  getApprovalRulesPolicy(userId: string): Promise<PolicyRead> {
    return this.request<PolicyRead>(
      `/v1/policies/approval-rules?${new URLSearchParams({ user_id: userId }).toString()}`,
    );
  }

  putApprovalRulesPolicy(userId: string, rules: Record<string, boolean>): Promise<PolicyRead> {
    return this.request<PolicyRead>("/v1/policies/approval-rules", {
      method: "PUT",
      body: JSON.stringify({ user_id: userId, rules }),
    });
  }

  listProviders(): Promise<ProviderStatusDetail[]> {
    return this.request<ProviderStatusDetail[]>("/v1/providers");
  }

  getNodeIdentity(): Promise<NodeIdentityRead> {
    return this.request<NodeIdentityRead>("/v1/node/identity");
  }

  getAgentIdentity(userId: string): Promise<AgentIdentityRead> {
    return this.request<AgentIdentityRead>(
      `/v1/agent/identity?user_id=${encodeURIComponent(userId)}`,
    );
  }

  getRelayStatus(): Promise<RelayStatusRead> {
    return this.request<RelayStatusRead>("/v1/relay/status");
  }

  listPeers(): Promise<PeerRead[]> {
    return this.request<PeerRead[]>("/v1/peers");
  }

  createPeer(params: PeerCreateParams): Promise<PeerRead> {
    return this.request<PeerRead>("/v1/peers", {
      method: "POST",
      body: JSON.stringify(params),
    });
  }

  trustPeer(agentId: string): Promise<PeerRead> {
    return this.request<PeerRead>(`/v1/peers/${encodeURIComponent(agentId)}/trust`, {
      method: "POST",
    });
  }

  blockPeer(agentId: string): Promise<PeerRead> {
    return this.request<PeerRead>(`/v1/peers/${encodeURIComponent(agentId)}/block`, {
      method: "POST",
    });
  }

  getPeerDisclosure(agentId: string): Promise<PeerDisclosurePolicyRead> {
    return this.request<PeerDisclosurePolicyRead>(
      `/v1/peers/${encodeURIComponent(agentId)}/disclosure`,
    );
  }

  putPeerDisclosure(
    agentId: string,
    policy: Omit<PeerDisclosurePolicyRead, "peer_agent_id" | "created_at" | "updated_at">,
  ): Promise<PeerDisclosurePolicyRead> {
    return this.request<PeerDisclosurePolicyRead>(
      `/v1/peers/${encodeURIComponent(agentId)}/disclosure`,
      {
        method: "PUT",
        body: JSON.stringify(policy),
      },
    );
  }

  listClones(userId: string): Promise<CloneRead[]> {
    return this.request<CloneRead[]>(`/v1/clones/${userId}`);
  }

  ensureClone(userId: string, purpose: string, providerType: string): Promise<CloneRead> {
    return this.request<CloneRead>(`/v1/clones/${userId}/ensure`, {
      method: "POST",
      body: JSON.stringify({ purpose, provider_type: providerType }),
    });
  }

  listNegotiations(): Promise<NegotiationRead[]> {
    return this.request<NegotiationRead[]>("/v1/negotiations");
  }

  createNegotiation(params: AnyNegotiationCreateParams): Promise<NegotiationRead> {
    return this.request<NegotiationRead>("/v1/negotiations", {
      method: "POST",
      body: JSON.stringify(params),
    });
  }

  createAgentRequest(params: AgentRequestCreateParams): Promise<NegotiationRead> {
    return this.request<NegotiationRead>("/v1/agent/requests", {
      method: "POST",
      body: JSON.stringify(params),
    });
  }

  listNegotiationMessages(sessionId: string): Promise<NegotiationMessageRead[]> {
    return this.request<NegotiationMessageRead[]>(`/v1/negotiations/${sessionId}/messages`);
  }

  getNegotiationMetrics(sessionId: string): Promise<NegotiationMetrics> {
    return this.request<NegotiationMetrics>(`/v1/metrics/negotiations/${sessionId}`);
  }

  getNegotiationDecision(sessionId: string): Promise<NegotiationDecisionRead | null> {
    return this.request<NegotiationDecisionRead | null>(
      `/v1/negotiations/${encodeURIComponent(sessionId)}/decision`,
    );
  }

  getMetricsSummary(): Promise<MetricsSummary> {
    return this.request<MetricsSummary>("/v1/metrics/summary");
  }

  runMetricsExperiment(params: {
    template: string;
    round_trips: number;
    uses_delta: boolean;
  }): Promise<MetricsExperimentRead> {
    return this.request<MetricsExperimentRead>("/v1/metrics/experiments", {
      method: "POST",
      body: JSON.stringify(params),
    });
  }

  listAgreements(filters: { status?: string; intent?: string } = {}): Promise<AgreementRead[]> {
    const params = new URLSearchParams();
    if (filters.status) params.set("status", filters.status);
    if (filters.intent) params.set("intent", filters.intent);
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return this.request<AgreementRead[]>(`/v1/agreements${suffix}`);
  }

  getAgreement(agreementId: string): Promise<AgreementRead> {
    return this.request<AgreementRead>(`/v1/agreements/${encodeURIComponent(agreementId)}`);
  }

  patchAgreementStatus(
    agreementId: string,
    status: "active" | "fulfilled" | "cancelled",
  ): Promise<AgreementRead> {
    return this.request<AgreementRead>(`/v1/agreements/${encodeURIComponent(agreementId)}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    });
  }

  listApprovals(userId?: string): Promise<ApprovalRead[]> {
    const suffix = userId ? `?${new URLSearchParams({ user_id: userId }).toString()}` : "";
    return this.request<ApprovalRead[]>(`/v1/approvals${suffix}`);
  }

  approveApproval(approvalId: string): Promise<ApprovalRead> {
    return this.request<ApprovalRead>(`/v1/approvals/${encodeURIComponent(approvalId)}/approve`, {
      method: "POST",
    });
  }

  rejectApproval(approvalId: string): Promise<ApprovalRead> {
    return this.request<ApprovalRead>(`/v1/approvals/${encodeURIComponent(approvalId)}/reject`, {
      method: "POST",
    });
  }
}
