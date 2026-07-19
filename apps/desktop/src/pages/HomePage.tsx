import { useState } from "react";
import { UpdateControl } from "../components/UpdateControl";
import type { ApiClient } from "../services/api";
import { useAppStore } from "../stores/appStore";

function providerLabel(provider: string): string {
  return provider === "codex" ? "Codex" : provider === "claude_code" ? "Claude Code" : provider;
}

export function HomePage({ client }: { client: ApiClient | null }) {
  const [requestText, setRequestText] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const { loading, error, health, environment, clones, peers, negotiations, approvals, agreements, metrics, users, relayStatus, requesting, requestError, requestCandidates, submitAgentRequest } =
    useAppStore();

  async function submitRequest(peerAgentId?: string) {
    if (!client || !users[0] || !requestText.trim()) return;
    const ok = await submitAgentRequest(client, users[0].id, requestText.trim(), peerAgentId);
    if (ok) {
      setRequestText("");
      setSubmitted(true);
    }
  }

  const activePeers = peers.filter((peer) => peer.status === "trusted").length;
  const activeNegotiations = negotiations.filter((session) =>
    ["open", "waiting_approval"].includes(session.status),
  ).length;
  const pendingApprovals = approvals.filter((approval) => approval.status === "pending").length;
  const emailTokens = metrics?.methods.find((method) => method.method === "email")?.total_tokens ?? 0;
  const structuredTokens =
    metrics?.methods.find((method) => method.method === "structured")?.total_tokens ?? 0;
  const savedTokens = emailTokens - structuredTokens;

  const rows: Array<[string, string, boolean]> = [
    ["macOS", environment ? `${environment.macos_version} · ${environment.architecture}` : "確認中", Boolean(environment)],
    ["Local Core", health ? `接続済み · v${health.version}` : error ? "未接続" : "接続中", Boolean(health)],
    ["データベース", health?.database_connected ? "接続済み" : "未接続", Boolean(health?.database_connected)],
    [
      "Relay自動受信",
      !relayStatus?.configured
        ? "未設定"
        : relayStatus.last_error
          ? "再接続中"
          : `稼働中 · ${relayStatus.processed_total}件受信`,
      Boolean(relayStatus?.configured && relayStatus.running && !relayStatus.last_error),
    ],
  ];

  for (const provider of environment?.providers ?? []) {
    rows.push([
      providerLabel(provider.provider),
      provider.installed ? provider.version ?? "検出済み" : "未検出", provider.installed,
    ]);
  }

  return (
    <main className="page home-page">
      <header className="page-header home-header"><div><p className="eyebrow">OVERVIEW</p><h1>おかえりなさい</h1><p className="subtitle">代理AIと接続環境の現在の状態です。</p></div><div className="agent-avatar">縁</div></header>
      {error && (
        <p role="alert" className="alert error">
          Local Coreへ接続できません: {error}
        </p>
      )}
      <section className="agent-request-panel">
        <div><p className="eyebrow">ASK YOUR AGENT</p><h2>代理AIへ依頼</h2><p>相手との調整は代理AI同士で進め、判断が必要なときだけ確認します。</p></div>
        <textarea
          value={requestText}
          onChange={(event) => { setRequestText(event.target.value); setSubmitted(false); }}
          placeholder="例: 2026-07-20に30分、13:00〜17:00で打ち合わせ"
          rows={3}
          aria-label="代理AIへの依頼"
        />
        <div className="agent-request-actions">
          <span>{requestError ?? (submitted ? "代理AIが交渉を開始しました。" : "日付・所要時間・時間帯を明記してください。")}</span>
          <button className="primary-button" onClick={() => void submitRequest()} disabled={!client || !users[0] || !requestText.trim() || requesting}>{requesting ? "依頼中…" : "代理AIに任せる"}</button>
        </div>
        {requestCandidates.length > 0 && (
          <div className="agent-request-candidates" role="group" aria-label="依頼する相手を選択">
            <strong>依頼する相手を選択</strong>
            {requestCandidates.map((candidate) => (
              <button
                key={candidate.agent_id}
                className="secondary-button"
                onClick={() => void submitRequest(candidate.agent_id)}
                disabled={requesting}
              >
                {candidate.display_name}
              </button>
            ))}
          </div>
        )}
      </section>
      <section className="stat-grid">
        <article className="stat-card accent"><span>未処理の承認</span><strong>{pendingApprovals}</strong><small>{pendingApprovals ? "確認が必要です" : "すべて確認済み"}</small></article>
        <article className="stat-card"><span>進行中の交渉</span><strong>{activeNegotiations}</strong><small>セッション</small></article>
        <article className="stat-card"><span>接続相手</span><strong>{activePeers}</strong><small>{peers.length}件中 trusted</small></article>
        <article className="stat-card"><span>成立した合意</span><strong>{agreements.length}</strong><small>件</small></article>
      </section>
      <div className="dashboard-grid">
        <section className="panel"><div className="panel-header"><div><h2>代理AI</h2><p>あなたの代わりに調整するエージェント</p></div><span className={`pill ${clones.length ? "success" : ""}`}>{clones.length ? "稼働中" : "未設定"}</span></div><div className="agent-row"><div className="agent-avatar small">AI</div><div><strong>{clones[0]?.name ?? "代理AIを設定"}</strong><p>{clones[0]?.status ?? "プロフィールと権限を設定してください"}</p></div></div></section>
        <section className="panel"><div className="panel-header"><div><h2>システム状態</h2><p>ローカル環境とAIプロバイダー</p></div></div><dl className="status-list">{rows.map(([label, value, ok]) => <div key={label}><dt><span className={`status-dot ${ok ? "online" : ""}`} />{label}</dt><dd>{loading && !health ? "…" : value}</dd></div>)}</dl></section>
      </div>
      <section className="savings-banner"><div><span className="savings-icon">⌁</span><div><strong>{Math.max(0, savedTokens).toLocaleString()} tokens</strong><p>構造化された交渉による推定削減量</p></div></div><span className="pill success">効率化</span></section>
      <UpdateControl />
    </main>
  );
}
