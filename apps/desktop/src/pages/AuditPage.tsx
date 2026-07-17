import { useEffect, useMemo, useState } from "react";
import type { ApiClient } from "../services/api";
import type { AuditLogRead } from "../types";

const eventMeta: Record<string, { label: string; description: string; group: string; tone: string }> = {
  clone_bootstrap_completed: { label: "代理AIを構築", description: "本人の記憶からクローンを生成しました", group: "agent", tone: "agent" },
  peer_registered: { label: "接続相手を登録", description: "公開鍵の指紋を確認できる状態にしました", group: "trust", tone: "trust" },
  peer_trusted: { label: "接続相手を信頼", description: "本人の確認を経て通信を許可しました", group: "trust", tone: "trust" },
  peer_blocked: { label: "接続相手をブロック", description: "この相手との通信を停止しました", group: "security", tone: "danger" },
  peer_disclosure_policy_updated: { label: "情報開示ルールを更新", description: "相手へ見せてよい情報の範囲を変更しました", group: "security", tone: "security" },
  remote_negotiation_started: { label: "代理交渉を開始", description: "署名付きメッセージをRelayへ送りました", group: "negotiation", tone: "negotiation" },
  inbox_processed: { label: "メッセージを検証", description: "受信メッセージの署名・順序・信頼関係を確認しました", group: "negotiation", tone: "negotiation" },
  approval_approved: { label: "本人が承認", description: "人間の最終判断を交渉結果へ反映しました", group: "approval", tone: "success" },
  approval_rejected: { label: "本人が拒否", description: "人間の拒否判断を相手へ返しました", group: "approval", tone: "danger" },
  approval_expired: { label: "承認が期限切れ", description: "古い承認では実行できないよう停止しました", group: "approval", tone: "danger" },
  agreement_created: { label: "合意を保存", description: "双方の代理AIで確定した結果を記録しました", group: "agreement", tone: "success" },
  agreement_status_changed: { label: "合意状態を更新", description: "合意の完了・取り消し状態を変更しました", group: "agreement", tone: "agreement" },
  envelope_rejected: { label: "不正メッセージを拒否", description: "検証に失敗したメッセージを隔離しました", group: "security", tone: "danger" },
  memory_updated: { label: "記憶を更新", description: "代理AIの判断材料が変更されました", group: "agent", tone: "agent" },
  memory_deleted: { label: "記憶を削除", description: "削除した記憶を今後の判断から除外しました", group: "agent", tone: "agent" },
};

const groupLabels: Record<string, string> = { all: "すべて", trust: "信頼", agent: "代理AI", negotiation: "交渉", approval: "承認", agreement: "合意", security: "安全性" };

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("ja-JP", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(value));
}

function payloadFacts(event: AuditLogRead): string[] {
  const facts: string[] = [];
  if (typeof event.payload.status === "string") facts.push(`状態: ${event.payload.status}`);
  if (typeof event.payload.intent === "string") facts.push(`種類: ${event.payload.intent}`);
  if (typeof event.payload.message_count === "number") facts.push(`メッセージ: ${event.payload.message_count}件`);
  if (typeof event.payload.processed === "number") facts.push(`検証: ${event.payload.processed}件`);
  if (typeof event.payload.memory_count === "number") facts.push(`記憶: ${event.payload.memory_count}件`);
  if (typeof event.payload.code === "string") facts.push(`理由: ${event.payload.code}`);
  if (typeof event.payload.max_sensitivity === "string") facts.push(`上限: ${event.payload.max_sensitivity}`);
  return facts;
}

export function AuditPage({ client }: { client: ApiClient | null }) {
  const [events, setEvents] = useState<AuditLogRead[]>([]);
  const [filter, setFilter] = useState("all");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    if (!client) return;
    setLoading(true);
    setError(null);
    try { setEvents(await client.listAuditEvents()); }
    catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, [client]);

  const groups = useMemo(() => [...new Set(events.map((event) => eventMeta[event.event_type]?.group ?? "security"))], [events]);
  const visible = filter === "all" ? events : events.filter((event) => (eventMeta[event.event_type]?.group ?? "security") === filter);
  const rejectedCount = events.filter((event) => event.event_type === "envelope_rejected").length;
  const approvalCount = events.filter((event) => event.event_type.startsWith("approval_")).length;

  return <main className="page audit-page">
    <header className="page-header"><div><p className="eyebrow">VERIFIABLE ACTIONS</p><h1>監査ログ</h1><p className="subtitle">代理AIが、いつ、何を、どの安全境界で行ったかを確認できます。</p></div><button onClick={() => void load()} disabled={loading}>{loading ? "更新中…" : "ログを更新"}</button></header>
    {error && <p role="alert" className="alert error">監査ログを取得できません: {error}</p>}
    <section className="audit-summary"><article><span>記録済みイベント</span><strong>{events.length}</strong></article><article><span>本人判断</span><strong>{approvalCount}</strong></article><article><span>拒否した不正通信</span><strong>{rejectedCount}</strong></article><article><span>保存内容</span><strong>メタデータのみ</strong></article></section>
    <div className="memory-toolbar"><div className="memory-filters"><button className={filter === "all" ? "selected" : ""} onClick={() => setFilter("all")}>すべて</button>{groups.map((group) => <button key={group} className={filter === group ? "selected" : ""} onClick={() => setFilter(group)}>{groupLabels[group] ?? group}</button>)}</div><span>{visible.length}件</span></div>
    {!error && !loading && events.length === 0 && <section className="empty-state"><div className="empty-icon">◷</div><h2>監査イベントはまだありません</h2><p>代理AIの作成や交渉を行うと、ここに安全な記録が残ります。</p></section>}
    <section className="audit-timeline">{visible.map((event) => {
      const meta = eventMeta[event.event_type] ?? { label: event.event_type, description: "システムイベントを記録しました", group: "security", tone: "security" };
      const facts = payloadFacts(event);
      return <article key={event.id} className="audit-event"><span className={`audit-marker ${meta.tone}`} /><div className="audit-event-card"><header><div><span className={`audit-kind ${meta.tone}`}>{groupLabels[meta.group] ?? "システム"}</span><strong>{meta.label}</strong></div><time>{formatDateTime(event.created_at)}</time></header><p>{meta.description}</p>{facts.length > 0 && <div className="audit-facts">{facts.map((fact) => <span key={fact}>{fact}</span>)}</div>}</div></article>;
    })}</section>
    {events.length > 0 && <section className="privacy-note"><strong>監査ログのプライバシー境界</strong><p>記憶本文、認証トークン、秘密鍵、公開鍵本文は表示APIから除外されます。ID・件数・状態など、動作検証に必要な最小限のメタデータだけを残します。</p></section>}
  </main>;
}
