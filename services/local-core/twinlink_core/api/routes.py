"""APIルーター。"""

import asyncio
import json
import secrets

from fastapi import APIRouter, Depends, WebSocket
from sqlalchemy import select
from sqlalchemy.orm import Session

from twinlink_core import __version__
from twinlink_core.api.deps import require_local_token
from twinlink_core.config import get_settings
from twinlink_core.database import get_session, is_connected
from twinlink_core.errors import TwinLinkError
from twinlink_core.models import (
    Approval,
    ApprovalStatus,
    CloneContextPackage,
    NegotiationDecision,
    User,
)
from twinlink_core.providers import get_adapter
from twinlink_core.providers.base import ProviderDetectionResult
from twinlink_core.schemas import (
    AgentIdentityRead,
    AgentRequestCreate,
    AgreementPatch,
    AgreementRead,
    ApprovalRead,
    CloneEnsureRequest,
    CloneRead,
    ContextPackageCreate,
    ContextPackageRead,
    DefaultDisclosurePolicyRead,
    EnvironmentInfo,
    HealthResponse,
    MemoryCreate,
    MemoryRead,
    MemorySourceSettingRead,
    MemorySourceSettingsUpdate,
    MetricsExperimentCreate,
    MetricsExperimentRead,
    MetricsSummary,
    NegotiationCreate,
    NegotiationDecisionRead,
    NegotiationMessageRead,
    NegotiationMetrics,
    NegotiationRead,
    NodeIdentityRead,
    PeerCreate,
    PeerDisclosurePolicyPatch,
    PeerDisclosurePolicyRead,
    PeerRead,
    PolicyRead,
    PolicyUpdate,
    ProjectCreate,
    ProjectPatch,
    ProjectRead,
    ProviderStatusDetail,
    RemoteNegotiationCreate,
    TaskCreate,
    TaskRead,
    UserCreate,
    UserRead,
    UserUpdate,
)
from twinlink_core.security.keys import ensure_node_keypair
from twinlink_core.services import agent_requests as agent_request_service
from twinlink_core.services import approvals as approval_service
from twinlink_core.services import (
    clone_bootstrap,
    context_builder,
    relay_worker,
    remote_negotiation,
)
from twinlink_core.services import clones as clone_service
from twinlink_core.services import memories as memory_service
from twinlink_core.services import memory_source_settings as memory_source_service
from twinlink_core.services import metrics as metrics_service
from twinlink_core.services import negotiation as negotiation_service
from twinlink_core.services import peers as peer_service
from twinlink_core.services import policies as policy_service
from twinlink_core.services import projects as project_service
from twinlink_core.services import tasks as task_service
from twinlink_core.services.environment import get_environment
from twinlink_core.services.relay_client import get_relay_client

health_router = APIRouter()

v1_router = APIRouter(prefix="/v1", dependencies=[Depends(require_local_token)])


@health_router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=__version__,
        database_connected=is_connected(),
    )


@v1_router.get("/system/environment", response_model=EnvironmentInfo)
def system_environment() -> EnvironmentInfo:
    return get_environment()


@v1_router.get("/users", response_model=list[UserRead])
def list_users(session: Session = Depends(get_session)) -> list[User]:
    return list(session.scalars(select(User).order_by(User.created_at)))


@v1_router.post("/users", response_model=UserRead, status_code=201)
def create_user(body: UserCreate, session: Session = Depends(get_session)) -> User:
    user = User(
        display_name=body.display_name,
        nickname=body.nickname,
        timezone=body.timezone,
        language=body.language,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    agent_request_service.ensure_personal_agent(session, user.id)
    session.commit()
    return user


@v1_router.put("/users/{user_id}", response_model=UserRead)
def update_user(
    user_id: str,
    body: UserUpdate,
    session: Session = Depends(get_session),
) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise TwinLinkError(
            code="USER_NOT_FOUND",
            message="ユーザーが見つかりません。",
            status_code=404,
            details={"user_id": user_id},
        )
    user.display_name = body.display_name
    user.nickname = body.nickname
    user.timezone = body.timezone
    user.language = body.language
    session.commit()
    session.refresh(user)
    return user


@v1_router.get("/clones/{user_id}", response_model=list[CloneRead])
def list_clones(user_id: str, session: Session = Depends(get_session)) -> list[CloneRead]:
    return [CloneRead.model_validate(c) for c in clone_service.list_clones(session, user_id)]


@v1_router.post("/clones/{user_id}/ensure", response_model=CloneRead)
def ensure_clone(
    user_id: str,
    body: CloneEnsureRequest,
    session: Session = Depends(get_session),
) -> CloneRead:
    clone, _created = clone_service.ensure_clone(
        session,
        user_id=user_id,
        purpose=body.purpose,
        provider_type=body.provider_type,
        project_id=body.project_id,
    )
    return CloneRead.model_validate(clone)


@v1_router.post("/clones/{clone_id}/activate", response_model=CloneRead)
def activate_clone(clone_id: str, session: Session = Depends(get_session)) -> CloneRead:
    return CloneRead.model_validate(clone_service.activate_clone(session, clone_id))


@v1_router.post("/clones/{clone_id}/rebuild", response_model=CloneRead)
def rebuild_clone(clone_id: str, session: Session = Depends(get_session)) -> CloneRead:
    return CloneRead.model_validate(clone_bootstrap.rebuild_clone(session, clone_id))


@v1_router.get("/memories", response_model=list[MemoryRead])
def list_memories(user_id: str, session: Session = Depends(get_session)) -> list[MemoryRead]:
    return [MemoryRead.model_validate(m) for m in memory_service.list_memories(session, user_id)]


@v1_router.get("/memory-sources", response_model=list[MemorySourceSettingRead])
def list_memory_sources(
    session: Session = Depends(get_session),
) -> list[MemorySourceSettingRead]:
    return [
        MemorySourceSettingRead.model_validate(source)
        for source in memory_source_service.list_settings(session)
    ]


@v1_router.put("/memory-sources", response_model=list[MemorySourceSettingRead])
def put_memory_sources(
    body: MemorySourceSettingsUpdate,
    session: Session = Depends(get_session),
) -> list[MemorySourceSettingRead]:
    return [
        MemorySourceSettingRead.model_validate(source)
        for source in memory_source_service.put_settings(
            session, [item.model_dump() for item in body.sources]
        )
    ]


@v1_router.post("/memories", response_model=MemoryRead, status_code=201)
def create_memory(body: MemoryCreate, session: Session = Depends(get_session)) -> MemoryRead:
    memory = memory_service.create_memory(
        session,
        user_id=body.user_id,
        source_type=body.source_type,
        source_reference=body.source_reference,
        memory_type=body.memory_type,
        title=body.title,
        content=body.content,
        searchable_text=body.searchable_text,
        confidence=body.confidence,
        sensitivity=body.sensitivity,
        relevance_tags=body.relevance_tags,
        effective_from=body.effective_from,
        effective_until=body.effective_until,
    )
    return MemoryRead.model_validate(memory)


@v1_router.delete("/memories/{memory_id}", response_model=MemoryRead)
def delete_memory(memory_id: str, session: Session = Depends(get_session)) -> MemoryRead:
    return MemoryRead.model_validate(memory_service.delete_memory(session, memory_id))


@v1_router.get("/projects", response_model=list[ProjectRead])
def list_projects(user_id: str, session: Session = Depends(get_session)) -> list[ProjectRead]:
    return [ProjectRead.model_validate(p) for p in project_service.list_projects(session, user_id)]


@v1_router.post("/projects", response_model=ProjectRead, status_code=201)
def create_project(body: ProjectCreate, session: Session = Depends(get_session)) -> ProjectRead:
    project = project_service.create_project(
        session,
        user_id=body.user_id,
        name=body.name,
        root_path=body.root_path,
    )
    return ProjectRead.model_validate(project)


@v1_router.get("/projects/{project_id}", response_model=ProjectRead)
def get_project(project_id: str, session: Session = Depends(get_session)) -> ProjectRead:
    return ProjectRead.model_validate(project_service.get_project(session, project_id))


@v1_router.patch("/projects/{project_id}", response_model=ProjectRead)
def patch_project(
    project_id: str,
    body: ProjectPatch,
    session: Session = Depends(get_session),
) -> ProjectRead:
    project = project_service.patch_project(
        session,
        project_id,
        permissions=body.permissions,
        trusted=body.trusted,
    )
    return ProjectRead.model_validate(project)


@v1_router.get("/approvals", response_model=list[ApprovalRead])
def list_approvals(
    user_id: str | None = None,
    session: Session = Depends(get_session),
) -> list[ApprovalRead]:
    approvals = approval_service.list_approvals(session, user_id)
    return [ApprovalRead.model_validate(a) for a in approvals]


@v1_router.post("/approvals/{approval_id}/approve", response_model=ApprovalRead)
def approve_approval(approval_id: str, session: Session = Depends(get_session)) -> ApprovalRead:
    pending = session.get(Approval, approval_id)
    if (
        pending is not None
        and pending.action_type == "negotiation_decision"
        and pending.payload.get("remote")
    ):
        approval = remote_negotiation.resolve_remote_approval(
            session, approval_id, ApprovalStatus.APPROVED.value
        )
        try:
            remote_negotiation.flush_outbox(session, get_relay_client())
        except TwinLinkError:
            pass
        return ApprovalRead.model_validate(approval)
    approval = approval_service.approve(session, approval_id)
    task_service.on_approval_resolved(session, approval)
    negotiation_service.on_approval_resolved(session, approval)
    return ApprovalRead.model_validate(approval)


@v1_router.post("/approvals/{approval_id}/reject", response_model=ApprovalRead)
def reject_approval(approval_id: str, session: Session = Depends(get_session)) -> ApprovalRead:
    pending = session.get(Approval, approval_id)
    if (
        pending is not None
        and pending.action_type == "negotiation_decision"
        and pending.payload.get("remote")
    ):
        approval = remote_negotiation.resolve_remote_approval(
            session, approval_id, ApprovalStatus.REJECTED.value
        )
        try:
            remote_negotiation.flush_outbox(session, get_relay_client())
        except TwinLinkError:
            pass
        return ApprovalRead.model_validate(approval)
    approval = approval_service.reject(session, approval_id)
    task_service.on_approval_resolved(session, approval)
    negotiation_service.on_approval_resolved(session, approval)
    return ApprovalRead.model_validate(approval)


async def _provider_status(provider: str) -> ProviderStatusDetail:
    adapter = get_adapter(provider)
    detection, authentication, capabilities = await asyncio.gather(
        adapter.detect(),
        adapter.check_authentication(),
        adapter.get_capabilities(),
    )
    return ProviderStatusDetail(
        provider=provider,
        installed=detection.installed,
        path=detection.path,
        version=detection.version,
        authenticated=authentication.authenticated,
        can_execute=capabilities.can_execute,
    )


@v1_router.get("/providers", response_model=list[ProviderStatusDetail])
async def list_providers() -> list[ProviderStatusDetail]:
    return [
        await _provider_status("codex"),
        await _provider_status("claude_code"),
        await _provider_status("mock"),
    ]


@v1_router.post("/providers/{provider}/detect", response_model=ProviderDetectionResult)
async def detect_provider(provider: str) -> ProviderDetectionResult:
    return await get_adapter(provider).detect()


@v1_router.post("/context-packages", response_model=ContextPackageRead)
def create_context_package(
    body: ContextPackageCreate,
    session: Session = Depends(get_session),
) -> ContextPackageRead:
    package = context_builder.build_context_package(
        session,
        clone_id=body.clone_id,
        task_goal=body.task_goal,
        project_id=body.project_id,
        peer_agent_id=body.peer_agent_id,
    )
    return ContextPackageRead.model_validate(package)


@v1_router.get("/context-packages/{package_id}", response_model=ContextPackageRead)
def get_context_package(
    package_id: str,
    session: Session = Depends(get_session),
) -> ContextPackageRead:
    package = session.get(CloneContextPackage, package_id)
    if package is None:
        raise TwinLinkError(
            code="CONTEXT_PACKAGE_NOT_FOUND",
            message="コンテキストパッケージが見つかりません。",
            status_code=404,
            details={"package_id": package_id},
        )
    return ContextPackageRead.model_validate(package)


@v1_router.post("/tasks", response_model=TaskRead, status_code=201)
def create_task(body: TaskCreate, session: Session = Depends(get_session)) -> TaskRead:
    task = task_service.create_task(
        session,
        user_id=body.user_id,
        clone_id=body.clone_id,
        provider=body.provider,
        description=body.description,
        project_id=body.project_id,
        requested_operations=body.requested_operations,
        approval_expires_at=body.approval_expires_at,
    )
    return TaskRead.model_validate(task)


@v1_router.get("/tasks/{task_id}", response_model=TaskRead)
def get_task(task_id: str, session: Session = Depends(get_session)) -> TaskRead:
    return TaskRead.model_validate(task_service.get_task(session, task_id))


@v1_router.post("/tasks/{task_id}/cancel", response_model=TaskRead)
def cancel_task(task_id: str, session: Session = Depends(get_session)) -> TaskRead:
    return TaskRead.model_validate(task_service.cancel_task(session, task_id))


def _websocket_authorized(websocket: WebSocket) -> bool:
    expected = get_settings().local_token
    authorization = websocket.headers.get("authorization")
    provided = ""
    if authorization is not None and authorization.startswith("Bearer "):
        provided = authorization.removeprefix("Bearer ")
    return bool(expected) and secrets.compare_digest(provided, expected)


@v1_router.websocket("/tasks/{task_id}/stream")
async def stream_task(task_id: str, websocket: WebSocket) -> None:
    await websocket.accept()
    if not _websocket_authorized(websocket):
        await websocket.close(code=1008)
        return

    session_iter = get_session()
    session = next(session_iter)
    try:
        task = task_service.get_task(session, task_id)
        for line in task.output_lines:
            await websocket.send_text(line)
        if task.status in {"completed", "failed", "cancelled"}:
            await websocket.send_text(json.dumps({"event": "end", "status": task.status}))
            await websocket.close()
    finally:
        session.close()


@v1_router.get("/metrics/summary", response_model=MetricsSummary)
def metrics_summary(session: Session = Depends(get_session)) -> MetricsSummary:
    return metrics_service.summarize_metrics(session)


@v1_router.post("/metrics/experiments", response_model=MetricsExperimentRead)
def run_metrics_experiment(
    body: MetricsExperimentCreate,
    session: Session = Depends(get_session),
) -> MetricsExperimentRead:
    return metrics_service.run_experiment(
        session,
        template=body.template,
        round_trips=body.round_trips,
        uses_delta=body.uses_delta,
    )


@v1_router.post("/negotiations", response_model=NegotiationRead, status_code=201)
def create_negotiation(
    body: NegotiationCreate,
    session: Session = Depends(get_session),
) -> NegotiationRead:
    if body.intent == negotiation_service.INTENT_TASK_REQUEST:
        if body.title is None:
            raise TwinLinkError(
                code="INVALID_NEGOTIATION_PAYLOAD",
                message="task.request には title が必要です。",
                status_code=422,
                details={"field": "title"},
            )
        negotiation = negotiation_service.run_task_request_negotiation(
            session,
            initiator_user_id=body.initiator_user_id,
            responder_user_id=body.responder_user_id,
            title=body.title,
            description=body.description,
            deadline=body.deadline,
            estimated_hours=body.estimated_hours,
            conditions=body.conditions,
        )
    else:
        if (
            body.topic is None
            or body.duration_minutes is None
            or body.date_range is None
            or not body.preferred_time_ranges
        ):
            raise TwinLinkError(
                code="INVALID_NEGOTIATION_PAYLOAD",
                message=(
                    "meeting.schedule には topic, duration_minutes, date_range, "
                    "preferred_time_ranges が必要です。"
                ),
                status_code=422,
                details={"intent": body.intent},
            )
        negotiation = negotiation_service.run_negotiation(
            session,
            initiator_user_id=body.initiator_user_id,
            responder_user_id=body.responder_user_id,
            topic=body.topic,
            duration_minutes=body.duration_minutes,
            date_range=body.date_range.model_dump(),
            preferred_time_ranges=[r.model_dump() for r in body.preferred_time_ranges],
        )
    return NegotiationRead.model_validate(negotiation)


@v1_router.post("/remote-negotiations", response_model=NegotiationRead, status_code=201)
def start_remote_negotiation(
    body: RemoteNegotiationCreate,
    session: Session = Depends(get_session),
) -> NegotiationRead:
    negotiation = remote_negotiation.start_remote_negotiation(
        session,
        get_relay_client(),
        user_id=body.user_id,
        peer_agent_id=body.peer_agent_id,
        topic=body.topic,
        duration_minutes=body.duration_minutes,
        date_range=body.date_range.model_dump(),
        preferred_time_ranges=[r.model_dump() for r in body.preferred_time_ranges],
    )
    return NegotiationRead.model_validate(negotiation)


@v1_router.post("/agent/requests", response_model=NegotiationRead, status_code=201)
def create_agent_request(
    body: AgentRequestCreate,
    session: Session = Depends(get_session),
) -> NegotiationRead:
    # Relay設定の解決より先に検証し、曖昧入力を必ず422かつ無送信で返す。
    agent_request_service.interpret_meeting_request(body.text)
    negotiation = agent_request_service.submit_agent_request(
        session,
        get_relay_client(),
        user_id=body.user_id,
        text=body.text,
        peer_agent_id=body.peer_agent_id,
    )
    return NegotiationRead.model_validate(negotiation)


@v1_router.post("/relay/inbox/process")
def process_relay_inbox(session: Session = Depends(get_session)) -> dict[str, object]:
    return dict(relay_worker.sync_session(session, get_relay_client()))


@v1_router.get("/relay/status")
def relay_status() -> dict[str, object]:
    return dict(relay_worker.status())


@v1_router.post("/relay/sync")
def sync_relay(session: Session = Depends(get_session)) -> dict[str, object]:
    return dict(relay_worker.sync_session(session, get_relay_client()))


@v1_router.get("/negotiations", response_model=list[NegotiationRead])
def list_negotiations(
    limit: int = 20,
    session: Session = Depends(get_session),
) -> list[NegotiationRead]:
    return [
        NegotiationRead.model_validate(n)
        for n in negotiation_service.list_negotiations(session, limit)
    ]


@v1_router.get("/negotiations/{session_id}", response_model=NegotiationRead)
def get_negotiation(session_id: str, session: Session = Depends(get_session)) -> NegotiationRead:
    return NegotiationRead.model_validate(
        negotiation_service.get_negotiation(session, session_id)
    )


@v1_router.get(
    "/negotiations/{session_id}/decision",
    response_model=NegotiationDecisionRead | None,
)
def get_negotiation_decision(
    session_id: str,
    session: Session = Depends(get_session),
) -> NegotiationDecisionRead | None:
    negotiation_service.get_negotiation(session, session_id)
    decision = session.scalars(
        select(NegotiationDecision)
        .where(NegotiationDecision.session_id == session_id)
        .order_by(NegotiationDecision.created_at.desc())
    ).first()
    return NegotiationDecisionRead.model_validate(decision) if decision else None


@v1_router.get("/negotiations/{session_id}/messages", response_model=list[NegotiationMessageRead])
def list_negotiation_messages(
    session_id: str,
    session: Session = Depends(get_session),
) -> list[NegotiationMessageRead]:
    negotiation = negotiation_service.get_negotiation(session, session_id)
    return [
        NegotiationMessageRead(
            message_id=m.id,
            session_id=m.session_id,
            sender_agent_id=m.sender_agent_id,
            receiver_agent_id=m.receiver_agent_id,
            message_type=m.message_type,
            intent=m.intent,
            session_version=negotiation.session_version,
            payload=m.payload,
            delta=m.delta,
            requires_human_approval=m.requires_human_approval,
            created_at=m.created_at,
        )
        for m in negotiation_service.list_messages(session, session_id)
    ]


@v1_router.get("/metrics/negotiations/{session_id}", response_model=NegotiationMetrics)
def negotiation_metrics(
    session_id: str,
    session: Session = Depends(get_session),
) -> NegotiationMetrics:
    return metrics_service.negotiation_metrics(session, session_id)


@v1_router.get("/agreements", response_model=list[AgreementRead])
def list_agreements(
    status: str | None = None,
    intent: str | None = None,
    session: Session = Depends(get_session),
) -> list[AgreementRead]:
    return [
        AgreementRead.model_validate(agreement)
        for agreement in negotiation_service.list_agreements(
            session, status=status, intent=intent
        )
    ]


@v1_router.get("/agreements/{agreement_id}", response_model=AgreementRead)
def get_agreement(
    agreement_id: str,
    session: Session = Depends(get_session),
) -> AgreementRead:
    return AgreementRead.model_validate(
        negotiation_service.get_agreement(session, agreement_id)
    )


@v1_router.patch("/agreements/{agreement_id}", response_model=AgreementRead)
def patch_agreement(
    agreement_id: str,
    body: AgreementPatch,
    session: Session = Depends(get_session),
) -> AgreementRead:
    return AgreementRead.model_validate(
        negotiation_service.patch_agreement_status(session, agreement_id, body.status)
    )


@v1_router.get("/node/identity", response_model=NodeIdentityRead)
def node_identity() -> NodeIdentityRead:
    # テストでdata_dirが変わるためlru_cacheせず毎回data_dir基準で解決する
    identity, _private_key = ensure_node_keypair(get_settings().data_dir)
    return NodeIdentityRead(
        agent_id=identity.agent_id,
        public_key=identity.public_key_b64,
        fingerprint=identity.fingerprint,
    )


@v1_router.get("/agent/identity", response_model=AgentIdentityRead)
def agent_identity(
    user_id: str,
    session: Session = Depends(get_session),
) -> AgentIdentityRead:
    personal = agent_request_service.ensure_personal_agent(session, user_id)
    node = agent_request_service.ensure_device_node(session, personal)
    session.commit()
    return AgentIdentityRead(
        personal_agent_id=personal.id,
        user_id=personal.user_id,
        active_clone_id=personal.active_clone_id,
        node_id=node.node_id,
        public_key=node.public_key,
        fingerprint=node.fingerprint,
    )


@v1_router.get("/peers", response_model=list[PeerRead])
def list_peers(session: Session = Depends(get_session)) -> list[PeerRead]:
    return [PeerRead.model_validate(p) for p in peer_service.list_peers(session)]


@v1_router.post("/peers", response_model=PeerRead, status_code=201)
def register_peer(body: PeerCreate, session: Session = Depends(get_session)) -> PeerRead:
    peer = peer_service.register_peer(
        session,
        agent_id=body.agent_id,
        personal_agent_id=body.personal_agent_id,
        display_name=body.display_name,
        public_key=body.public_key,
        aliases=body.aliases,
    )
    return PeerRead.model_validate(peer)


@v1_router.post("/peers/{agent_id}/trust", response_model=PeerRead)
def trust_peer(agent_id: str, session: Session = Depends(get_session)) -> PeerRead:
    return PeerRead.model_validate(peer_service.trust_peer(session, agent_id))


@v1_router.post("/peers/{agent_id}/block", response_model=PeerRead)
def block_peer(agent_id: str, session: Session = Depends(get_session)) -> PeerRead:
    return PeerRead.model_validate(peer_service.block_peer(session, agent_id))


@v1_router.get("/peers/{agent_id}/disclosure", response_model=PeerDisclosurePolicyRead)
def get_peer_disclosure(
    agent_id: str,
    session: Session = Depends(get_session),
) -> PeerDisclosurePolicyRead:
    return PeerDisclosurePolicyRead.model_validate(
        peer_service.get_disclosure_policy(session, agent_id)
    )


@v1_router.get("/disclosure/default", response_model=DefaultDisclosurePolicyRead)
def get_default_disclosure(
    session: Session = Depends(get_session),
) -> DefaultDisclosurePolicyRead:
    return DefaultDisclosurePolicyRead.model_validate(
        peer_service.get_default_disclosure_policy(session)
    )


@v1_router.put("/disclosure/default", response_model=DefaultDisclosurePolicyRead)
def put_default_disclosure(
    body: PeerDisclosurePolicyPatch,
    session: Session = Depends(get_session),
) -> DefaultDisclosurePolicyRead:
    return DefaultDisclosurePolicyRead.model_validate(
        peer_service.put_default_disclosure_policy(
            session,
            allowed_memory_types=list(body.allowed_memory_types),
            max_sensitivity=body.max_sensitivity,
            share_schedule=body.share_schedule,
            share_skills=body.share_skills,
            extra=body.extra,
        )
    )


@v1_router.get("/policies/delegation", response_model=PolicyRead)
def get_delegation_policy(
    user_id: str,
    session: Session = Depends(get_session),
) -> PolicyRead:
    return PolicyRead(
        **policy_service.policy_to_dict(policy_service.get_delegation(session, user_id))
    )


@v1_router.put("/policies/delegation", response_model=PolicyRead)
def put_delegation_policy(
    body: PolicyUpdate,
    session: Session = Depends(get_session),
) -> PolicyRead:
    return PolicyRead(
        **policy_service.policy_to_dict(
            policy_service.put_delegation(session, body.user_id, body.rules)
        )
    )


@v1_router.get("/policies/approval-rules", response_model=PolicyRead)
def get_approval_rules_policy(
    user_id: str,
    session: Session = Depends(get_session),
) -> PolicyRead:
    return PolicyRead(
        **policy_service.policy_to_dict(policy_service.get_approval_rules(session, user_id))
    )


@v1_router.put("/policies/approval-rules", response_model=PolicyRead)
def put_approval_rules_policy(
    body: PolicyUpdate,
    session: Session = Depends(get_session),
) -> PolicyRead:
    return PolicyRead(
        **policy_service.policy_to_dict(
            policy_service.put_approval_rules(session, body.user_id, body.rules)
        )
    )


@v1_router.put("/peers/{agent_id}/disclosure", response_model=PeerDisclosurePolicyRead)
def put_peer_disclosure(
    agent_id: str,
    body: PeerDisclosurePolicyPatch,
    session: Session = Depends(get_session),
) -> PeerDisclosurePolicyRead:
    return PeerDisclosurePolicyRead.model_validate(
        peer_service.put_disclosure_policy(
            session,
            agent_id=agent_id,
            allowed_memory_types=list(body.allowed_memory_types),
            max_sensitivity=body.max_sensitivity,
            share_schedule=body.share_schedule,
            share_skills=body.share_skills,
            extra=body.extra,
        )
    )
