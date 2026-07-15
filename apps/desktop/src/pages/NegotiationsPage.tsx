import { useEffect } from "react";
import type { ApiClient } from "../services/api";
import { useNegotiationStore } from "../stores/negotiationStore";
import { useAppStore } from "../stores/appStore";
import type { NegotiationDecisionRead, NegotiationMessageRead, NegotiationMetrics, NegotiationRead } from "../types";

function statusLabel(status: string): string {
  if (status === "agreed") return "合意済み";
  if (status === "failed") return "不成立";
  if (status === "waiting_approval") return "判断待ち";
  return "交渉中";
}

function intentLabel(intent: string): string {
  if (intent === "meeting.schedule") return "日程調整";
  if (intent === "task.request") return "仕事の依頼";
  return intent;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("ja-JP", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function messageLabel(type: string): string {
  const labels: Record<string, string> = { REQUEST: "依頼", PROPOSE: "提案", COUNTER: "代案", ACCEPT: "合意", REJECT: "拒否", REQUEST_APPROVAL: "人間へ判断を依頼", APPROVAL_RESULT: "判断結果", EXECUTE: "実行", RECEIPT: "完了" };
  return labels[type] ?? type;
}

const reasonLabels: Record<string, string> = {
  schedule_negotiation_not_delegated: "日程交渉が委任範囲外",
  clone_confidence_below_threshold: "判断の確信度が基準未満",
  meeting_auto_accept_disabled: "自動承認が無効",
  meeting_outside_preferred_time: "希望時間帯から外れている",
  meeting_time_avoided: "避けたい時間帯に含まれている",
  relationship_requires_approval: "この相手には本人確認が必要",
  common_slot_within_delegation: "委任範囲内の共通候補",
  no_common_slot: "共通候補なし",
};

function MessageBody({ message }: { message: NegotiationMessageRead }) {
  const body = Object.keys(message.delta).length > 0 ? message.delta : message.payload;
  if (message.message_type !== "REQUEST_APPROVAL") return <pre>{JSON.stringify(body, null, 2)}</pre>;
  const reasons = Array.isArray(body.reason_codes) ? body.reason_codes.filter((item): item is string => typeof item === "string") : [];
  const confidence = typeof body.confidence === "number" ? Math.round(body.confidence * 100) : null;
  return <div className="decision-explanation"><p><strong>本人確認の理由:</strong> {reasons.map((reason) => reasonLabels[reason] ?? reason).join("、")}</p><p><strong>代理AIの確信度:</strong> {confidence === null ? "—" : `${confidence}%`}</p></div>;
}

function MessageCard({ message, ownAgentIds }: { message: NegotiationMessageRead; ownAgentIds: Set<string> }) {
  const outgoing = ownAgentIds.has(message.sender_agent_id);
  return (
    <li className={`log-entry ${outgoing ? "outgoing" : "incoming"}`}>
      <div className="log-marker" />
      <div className="log-card">
        <div className="log-meta"><strong>{outgoing ? "あなたの代理AI" : "相手の代理AI"}</strong><span>{formatDate(message.created_at)}</span></div>
        <div className="log-action"><span className="pill">{messageLabel(message.message_type)}</span>{message.requires_human_approval && <span className="pill attention">判断が必要</span>}</div>
        <MessageBody message={message} />
      </div>
    </li>
  );
}

function DecisionSummary({ session, messages, decision, onOpenApprovals }: { session: NegotiationRead; messages: NegotiationMessageRead[]; decision: NegotiationDecisionRead | null; onOpenApprovals: () => void }) {
  const last = messages.at(-1);
  return (
    <section className={`decision-card ${session.pending_approval_id ? "needs-decision" : ""}`}>
      <div><p className="eyebrow">CURRENT POSITION</p><h2>{session.pending_approval_id ? "あなたの判断を待っています" : statusLabel(session.status)}</h2><p>{session.pending_approval_id ? "AI同士の交渉が一区切りつきました。条件と交渉ログを確認して決定してください。" : "AI同士が条件を調整しています。必要なときだけ承認を求めます。"}</p></div>
      {session.pending_approval_id && <button className="primary-button" onClick={onOpenApprovals}>条件を確認して判断する</button>}
      {decision && <div className="decision-explanation"><p><strong>代理AIの判断:</strong> {decision.reason_codes.map((reason) => reasonLabels[reason] ?? reason).join("、")}</p><p><strong>判断の確信度:</strong> {Math.round(decision.confidence * 100)}%</p></div>}
      <dl className="decision-facts"><div><dt>交渉内容</dt><dd>{session.topic}</dd></div><div><dt>種類</dt><dd>{intentLabel(session.intent)}</dd></div><div><dt>現在の段階</dt><dd>{last ? messageLabel(last.message_type) : "開始待ち"}</dd></div><div><dt>更新</dt><dd>{formatDate(session.updated_at)}</dd></div></dl>
    </section>
  );
}

function MetricsPanel({ metrics }: { metrics: NegotiationMetrics }) {
  return <section className="negotiation-metrics"><span>交渉効率</span><strong>{metrics.reduction_rate === null ? "—" : `${metrics.reduction_rate.toFixed(0)}%`}</strong><small>通常のメール調整より少ないトークン</small></section>;
}

export function NegotiationsPage({ client, onOpenApprovals }: { client: ApiClient | null; onOpenApprovals: () => void }) {
  const { sessions, selectedSessionId, messages, metrics, decision, loading, error, loadSessions, select } = useNegotiationStore();
  const clones = useAppStore((state) => state.clones);
  const ownAgentIds = new Set(clones.map((clone) => clone.id));
  const selected = sessions.find((session) => session.id === selectedSessionId) ?? null;
  const waitingCount = sessions.filter((session) => session.pending_approval_id).length;

  useEffect(() => { if (client) void loadSessions(client); }, [client, loadSessions]);
  useEffect(() => { if (client && sessions.length > 0 && !selectedSessionId) { const priority = sessions.find((item) => item.pending_approval_id) ?? sessions[0]; void select(client, priority.id); } }, [client, sessions, selectedSessionId, select]);

  return (
    <main className="page negotiations-page">
      <header className="page-header"><div><p className="eyebrow">AI NEGOTIATIONS</p><h1>交渉</h1><p className="subtitle">AI同士の交渉状況を把握し、最終的な決定を行います。</p></div><div className={`decision-count ${waitingCount ? "active" : ""}`}><strong>{waitingCount}</strong><span>判断待ち</span></div></header>
      {error && <p role="alert" className="alert error">{error}</p>}
      <div className="negotiation-layout">
        <aside className="session-panel"><div className="session-panel-header"><h2>交渉一覧</h2><span>{sessions.length}件</span></div>{sessions.length === 0 && <div className="compact-empty">交渉履歴はありません</div>}<ul>{sessions.map((session) => <li key={session.id}><button onClick={() => client && void select(client, session.id)} className={`session-item ${session.id === selectedSessionId ? "selected" : ""}`}><div className="session-title"><span className={`session-status ${session.pending_approval_id ? "waiting" : session.status}`} /> <strong>{session.topic}</strong></div><p>{intentLabel(session.intent)} · {statusLabel(session.status)}</p><time>{formatDate(session.updated_at)}</time>{session.pending_approval_id && <span className="session-attention">要判断</span>}</button></li>)}</ul></aside>
        <div className="negotiation-detail">
          {!selected && <section className="empty-state"><div className="empty-icon">⇄</div><h2>{loading ? "読み込み中…" : "交渉を選択"}</h2><p>左の一覧から確認したい交渉を選んでください。</p></section>}
          {selected && <><DecisionSummary session={selected} messages={messages} decision={decision} onOpenApprovals={onOpenApprovals} /><section className="log-panel"><div className="log-panel-header"><div><h2>交渉ログ</h2><p>双方の代理AIが、何を提案しどう判断したかを時系列で表示します。</p></div><span>{messages.length}件</span></div>{loading ? <div className="compact-empty">ログを読み込んでいます…</div> : messages.length === 0 ? <div className="compact-empty">ログはまだありません</div> : <ol className="log-timeline">{messages.map((message) => <MessageCard key={message.message_id} message={message} ownAgentIds={ownAgentIds} />)}</ol>}</section>{metrics && <MetricsPanel metrics={metrics} />}</>}
        </div>
      </div>
    </main>
  );
}
