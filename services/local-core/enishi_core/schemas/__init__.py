"""APIスキーマ（Pydantic）。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    version: str
    database_connected: bool


class ProviderStatus(BaseModel):
    provider: str
    installed: bool
    path: str | None = None
    version: str | None = None


class EnvironmentInfo(BaseModel):
    macos_version: str
    architecture: str
    is_apple_silicon: bool
    python_version: str
    providers: list[ProviderStatus]


class UserCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    nickname: str | None = Field(default=None, max_length=200)
    timezone: str = "Asia/Tokyo"
    language: str = "ja"


class UserUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    nickname: str | None = Field(default=None, max_length=200)
    timezone: str = Field(min_length=1, max_length=64)
    language: str = Field(min_length=1, max_length=16)


class UserRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    display_name: str
    nickname: str | None
    timezone: str
    language: str
    created_at: datetime
    updated_at: datetime


class CloneEnsureRequest(BaseModel):
    purpose: str = Field(min_length=1, max_length=500)
    provider_type: str = Field(pattern=r"^(codex|claude_code|mock)$")
    project_id: str | None = None


class CloneRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    user_id: str
    name: str
    version: int
    status: str
    coding_profile: dict[str, Any]
    confidence_score: float
    created_at: datetime
    activated_at: datetime | None


MemoryTypeLiteral = Literal[
    "identity",
    "preference",
    "skill",
    "project",
    "decision",
    "policy",
    "communication",
    "environment",
    "negative_preference",
    "episodic",
    "relationship",
    "schedule",
]

SensitivityLiteral = Literal["public", "internal", "private", "restricted", "secret"]


class MemoryCreate(BaseModel):
    user_id: str
    source_type: str = Field(min_length=1, max_length=64)
    source_reference: str | None = None
    memory_type: MemoryTypeLiteral
    title: str = Field(min_length=1, max_length=200)
    content: dict[str, Any] = Field(default_factory=dict)
    searchable_text: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    sensitivity: SensitivityLiteral = "internal"
    relevance_tags: list[str] = Field(default_factory=list)
    effective_from: datetime | None = None
    effective_until: datetime | None = None


class MemoryRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    user_id: str
    source_type: str
    source_reference: str | None
    memory_type: str
    title: str
    content: dict[str, Any]
    searchable_text: str | None
    confidence: float
    sensitivity: str
    relevance_tags: list[str]
    effective_from: datetime | None
    effective_until: datetime | None
    status: str
    created_at: datetime
    updated_at: datetime


class ProjectCreate(BaseModel):
    user_id: str
    name: str = Field(min_length=1, max_length=200)
    root_path: str = Field(min_length=1, max_length=1000)


class ProjectPatch(BaseModel):
    permissions: dict[str, bool] | None = None
    trusted: bool | None = None


class ProjectRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    user_id: str
    name: str
    root_path: str
    repository_type: str | None
    default_branch: str | None
    trusted: bool
    permissions: dict[str, Any]
    created_at: datetime
    last_opened_at: datetime | None


class ApprovalCreate(BaseModel):
    user_id: str
    action_type: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1000)
    level: int = Field(ge=0, le=3)
    payload: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None


class ApprovalRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    user_id: str
    action_type: str
    description: str
    level: int
    status: str
    payload: dict[str, Any]
    created_at: datetime
    expires_at: datetime
    resolved_at: datetime | None


class MethodMetricSummary(BaseModel):
    method: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    llm_calls: int
    message_count: int
    duration_ms: int


class MetricsSummary(BaseModel):
    methods: list[MethodMetricSummary]
    reduction_rate: float | None


class MetricsExperimentCreate(BaseModel):
    template: str = Field(min_length=1, max_length=4000)
    round_trips: int = Field(default=2, ge=1, le=10)
    uses_delta: bool = True


class MetricsExperimentRead(BaseModel):
    id: str
    template: str
    round_trips: int
    uses_delta: bool
    structured_json: dict[str, Any]
    methods: list[MethodMetricSummary]
    reduction_rate: float | None
    created_at: datetime


class DateRange(BaseModel):
    start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class TimeRange(BaseModel):
    start: str = Field(pattern=r"^\d{2}:\d{2}$")
    end: str = Field(pattern=r"^\d{2}:\d{2}$")


class NegotiationCreate(BaseModel):
    intent: Literal["meeting.schedule", "task.request"] = "meeting.schedule"
    initiator_user_id: str
    responder_user_id: str
    topic: str | None = Field(default=None, min_length=1, max_length=500)
    duration_minutes: int | None = Field(default=None, ge=1, le=480)
    date_range: DateRange | None = None
    preferred_time_ranges: list[TimeRange] = Field(default_factory=list)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str = ""
    deadline: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    estimated_hours: float | None = Field(default=None, ge=0.0)
    conditions: dict[str, Any] = Field(default_factory=dict)


class RemoteNegotiationCreate(BaseModel):
    user_id: str
    peer_agent_id: str
    topic: str = Field(min_length=1, max_length=500)
    duration_minutes: int = Field(ge=1, le=480)
    date_range: DateRange
    preferred_time_ranges: list[TimeRange] = Field(min_length=1)


class AgentRequestCreate(BaseModel):
    user_id: str
    text: str = Field(min_length=1, max_length=2000)
    peer_agent_id: str | None = None


class NegotiationRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    initiator_clone_id: str
    responder_clone_id: str
    initiator_agent_id: str | None
    responder_agent_id: str | None
    intent: str
    topic: str
    status: str
    session_version: int
    result: dict[str, Any]
    pending_approval_id: str | None
    created_at: datetime
    updated_at: datetime


class NegotiationMessageRead(BaseModel):
    protocol: str = "aun/0.1"
    message_id: str
    session_id: str
    sender_agent_id: str
    receiver_agent_id: str
    message_type: str
    intent: str
    session_version: int
    payload: dict[str, Any]
    delta: dict[str, Any]
    requires_human_approval: bool
    created_at: datetime


class NegotiationDecisionRead(BaseModel):
    model_config = {"from_attributes": True}

    policy_version: int
    outcome: str
    reason_codes: list[str]
    evidence: dict[str, Any]
    confidence: float
    created_at: datetime


class NegotiationMetrics(BaseModel):
    structured: MethodMetricSummary
    email: MethodMetricSummary
    reduction_rate: float | None


class ProviderStatusDetail(BaseModel):
    provider: str
    installed: bool
    path: str | None = None
    version: str | None = None
    authenticated: bool | None = None
    can_execute: bool


class ContextPackageCreate(BaseModel):
    clone_id: str
    task_goal: str = Field(min_length=1, max_length=2000)
    project_id: str | None = None
    peer_agent_id: str | None = None


class ContextPackageRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    clone_id: str
    clone_version: int
    task_id: str | None
    project_id: str | None
    task_goal: str
    relevant_preferences: dict[str, Any]
    relevant_skills: dict[str, Any]
    relevant_project_context: dict[str, Any]
    relevant_decisions: list[dict[str, Any]]
    coding_rules: list[Any]
    prohibited_actions: list[str]
    approval_requirements: list[str]
    file_references: list[str]
    estimated_tokens: int
    content_hash: str
    generated_at: datetime


ProviderLiteral = Literal["codex", "claude_code", "mock"]


class TaskCreate(BaseModel):
    user_id: str
    clone_id: str
    provider: ProviderLiteral
    description: str = Field(min_length=1, max_length=4000)
    project_id: str | None = None
    requested_operations: list[str] = Field(default_factory=list)
    approval_expires_at: datetime | None = None


class TaskRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    user_id: str
    clone_id: str
    project_id: str | None
    provider: str
    description: str
    status: str
    context_package_id: str | None
    approval_id: str | None
    output_lines: list[str]
    result: dict[str, Any]
    failure_code: str | None
    failure_message: str | None
    created_at: datetime
    queued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    worker_id: str | None
    heartbeat_at: datetime | None
    timeout_seconds: int


class NodeIdentityRead(BaseModel):
    agent_id: str
    public_key: str
    fingerprint: str


class AgentIdentityRead(BaseModel):
    personal_agent_id: str
    user_id: str
    active_clone_id: str | None
    node_id: str
    public_key: str
    fingerprint: str


class PeerCreate(BaseModel):
    agent_id: str = Field(min_length=1, max_length=64)
    personal_agent_id: str | None = Field(default=None, min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    public_key: str = Field(min_length=1, max_length=200)


class PeerRead(BaseModel):
    model_config = {"from_attributes": True}

    agent_id: str
    personal_agent_id: str | None
    display_name: str
    aliases: list[str]
    public_key: str
    fingerprint: str
    status: str
    created_at: datetime
    updated_at: datetime


class PeerDisclosurePolicyPatch(BaseModel):
    allowed_memory_types: list[MemoryTypeLiteral] = Field(default_factory=list)
    max_sensitivity: SensitivityLiteral = "internal"
    share_schedule: bool = True
    share_skills: bool = False
    extra: dict[str, Any] = Field(default_factory=dict)


class PeerDisclosurePolicyRead(BaseModel):
    model_config = {"from_attributes": True}

    peer_agent_id: str
    allowed_memory_types: list[str]
    max_sensitivity: str
    share_schedule: bool
    share_skills: bool
    extra: dict[str, Any]
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DefaultDisclosurePolicyRead(BaseModel):
    model_config = {"from_attributes": True}

    allowed_memory_types: list[str]
    max_sensitivity: str
    share_schedule: bool
    share_skills: bool
    extra: dict[str, Any]
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MemorySourceSettingPatch(BaseModel):
    source: str = Field(min_length=1, max_length=64)
    enabled: bool
    scope: str = Field(default="", max_length=500)


class MemorySourceSettingsUpdate(BaseModel):
    sources: list[MemorySourceSettingPatch]


class MemorySourceSettingRead(BaseModel):
    model_config = {"from_attributes": True}

    source: str
    connected: bool
    enabled: bool
    scope: str
    created_at: datetime
    updated_at: datetime


class PolicyRead(BaseModel):
    user_id: str
    name: str
    rules: dict[str, bool]
    enabled: bool
    created_at: datetime
    updated_at: datetime


class PolicyUpdate(BaseModel):
    user_id: str
    rules: dict[str, bool] = Field(default_factory=dict)


class AgreementPatch(BaseModel):
    status: Literal["active", "fulfilled", "cancelled"]


class AgreementRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    session_id: str
    intent: str
    initiator_agent_id: str
    responder_agent_id: str
    agreed_payload: dict[str, Any]
    status: str
    agreed_at: datetime
    updated_at: datetime
