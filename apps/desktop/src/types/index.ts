export interface CoreConnection {
  port: number;
  token: string;
}

export interface HealthResponse {
  status: string;
  version: string;
  database_connected: boolean;
}

export interface ProviderStatus {
  provider: string;
  installed: boolean;
  path: string | null;
  version: string | null;
}

export interface EnvironmentInfo {
  macos_version: string;
  architecture: string;
  is_apple_silicon: boolean;
  python_version: string;
  providers: ProviderStatus[];
}

export interface NodeIdentityRead {
  agent_id: string;
  public_key: string;
  fingerprint: string;
}

export interface UserRead {
  id: string;
  display_name: string;
  nickname: string | null;
  timezone: string;
  language: string;
  created_at: string;
  updated_at: string;
}

export interface UserUpdateParams {
  display_name: string;
  nickname: string | null;
  timezone: string;
  language: string;
}

export interface CloneRead {
  id: string;
  user_id: string;
  name: string;
  version: number;
  status: string;
  identity_profile: Record<string, unknown>;
  preference_profile: Record<string, unknown>;
  skill_profile: Record<string, unknown>;
  coding_profile: Record<string, unknown>;
  project_profile: Record<string, unknown>;
  policy_profile: Record<string, unknown>;
  communication_profile: Record<string, unknown>;
  memory_snapshot_id: string | null;
  confidence_score: number;
  created_at: string;
  activated_at: string | null;
}

export interface MemoryRead {
  id: string;
  user_id: string;
  source_type: string;
  source_reference: string | null;
  memory_type: string;
  title: string;
  content: Record<string, unknown>;
  searchable_text: string | null;
  confidence: number;
  sensitivity: "public" | "internal" | "private" | "restricted" | "secret" | string;
  relevance_tags: string[];
  effective_from: string | null;
  effective_until: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface NegotiationRead {
  id: string;
  initiator_clone_id: string;
  responder_clone_id: string;
  initiator_agent_id: string | null;
  responder_agent_id: string | null;
  intent: string;
  topic: string;
  status: string;
  session_version: number;
  result: Record<string, unknown>;
  pending_approval_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentRequestCreateParams {
  user_id: string;
  text: string;
  peer_agent_id?: string;
}

export interface NegotiationMessageRead {
  protocol: string;
  message_id: string;
  session_id: string;
  sender_agent_id: string;
  receiver_agent_id: string;
  message_type: string;
  intent: string;
  session_version: number;
  payload: Record<string, unknown>;
  delta: Record<string, unknown>;
  requires_human_approval: boolean;
  created_at: string;
}

export interface MethodMetricSummary {
  method: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  llm_calls: number;
  message_count: number;
  duration_ms: number;
}

export interface MetricsSummary {
  methods: MethodMetricSummary[];
  reduction_rate: number | null;
}

export interface MetricsExperimentRead {
  id: string;
  template: string;
  round_trips: number;
  uses_delta: boolean;
  structured_json: Record<string, unknown>;
  methods: MethodMetricSummary[];
  reduction_rate: number | null;
  created_at: string;
}

export interface NegotiationMetrics {
  structured: MethodMetricSummary;
  email: MethodMetricSummary;
  reduction_rate: number | null;
}

export interface NegotiationDecisionRead {
  policy_version: number;
  outcome: string;
  reason_codes: string[];
  evidence: Record<string, unknown>;
  confidence: number;
  created_at: string;
}

export interface NegotiationCreateParams {
  intent?: "meeting.schedule";
  initiator_user_id: string;
  responder_user_id: string;
  topic: string;
  duration_minutes: number;
  date_range: { start: string; end: string };
  preferred_time_ranges: Array<{ start: string; end: string }>;
}

export interface TaskNegotiationCreateParams {
  intent: "task.request";
  initiator_user_id: string;
  responder_user_id: string;
  title: string;
  description: string;
  deadline: string | null;
  estimated_hours: number | null;
  conditions: Record<string, unknown>;
}

export type AnyNegotiationCreateParams = NegotiationCreateParams | TaskNegotiationCreateParams;

export interface PeerRead {
  agent_id: string;
  personal_agent_id: string | null;
  display_name: string;
  aliases: string[];
  public_key: string;
  fingerprint: string;
  status: "pending" | "trusted" | "blocked" | string;
  created_at: string;
  updated_at: string;
}

export interface PeerCreateParams {
  agent_id: string;
  personal_agent_id?: string;
  display_name: string;
  aliases?: string[];
  public_key: string;
}

export interface AgentIdentityRead {
  personal_agent_id: string;
  user_id: string;
  active_clone_id: string | null;
  node_id: string;
  public_key: string;
  fingerprint: string;
}

export interface RelayStatusRead {
  configured: boolean;
  running: boolean;
  last_success: string | null;
  last_error: string | null;
  processed_total: number;
}

export interface PeerDisclosurePolicyRead {
  peer_agent_id: string;
  allowed_memory_types: string[];
  max_sensitivity: string;
  share_schedule: boolean;
  share_skills: boolean;
  extra: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
}

export interface DefaultDisclosurePolicyRead {
  allowed_memory_types: string[];
  max_sensitivity: string;
  share_schedule: boolean;
  share_skills: boolean;
  extra: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
}

export interface MemorySourceSettingRead {
  source: string;
  connected: boolean;
  enabled: boolean;
  scope: string;
  created_at: string;
  updated_at: string;
}

export interface MemorySourceSettingPatch {
  source: string;
  enabled: boolean;
  scope: string;
}

export interface PolicyRead {
  user_id: string;
  name: string;
  rules: Record<string, boolean>;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProviderStatusDetail {
  provider: string;
  installed: boolean;
  path: string | null;
  version: string | null;
  authenticated: boolean | null;
  can_execute: boolean;
}

export interface AgreementRead {
  id: string;
  session_id: string;
  intent: string;
  initiator_agent_id: string;
  responder_agent_id: string;
  agreed_payload: Record<string, unknown>;
  status: "active" | "fulfilled" | "cancelled" | string;
  agreed_at: string;
  updated_at: string;
}

export interface ApprovalRead {
  id: string;
  user_id: string;
  action_type: string;
  description: string;
  level: number;
  status: string;
  payload: Record<string, unknown>;
  created_at: string;
  expires_at: string;
  resolved_at: string | null;
}

export interface AuditLogRead {
  id: string;
  event_type: string;
  user_id: string | null;
  clone_id: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}
