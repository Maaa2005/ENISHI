import { useEffect, useState } from "react";
import { AgreementsPage } from "./pages/AgreementsPage";
import { AgentSetupPage } from "./pages/AgentSetupPage";
import { ApprovalsPage } from "./pages/ApprovalsPage";
import { HomePage } from "./pages/HomePage";
import { MetricsPage } from "./pages/MetricsPage";
import { NegotiationsPage } from "./pages/NegotiationsPage";
import { PeersPage } from "./pages/PeersPage";
import { ApiClient } from "./services/api";
import { resolveCoreConnection } from "./services/backend";
import { useAppStore } from "./stores/appStore";
import "./styles.css";

type Tab =
  | "home"
  | "agentSetup"
  | "peers"
  | "negotiations"
  | "agreements"
  | "approvals"
  | "memories"
  | "metrics"
  | "clones"
  | "projects"
  | "agents"
  | "tasks";

const TABS: Array<[Tab, string, string, string]> = [
  ["home", "概要", "⌂", "メイン"],
  ["approvals", "承認", "✓", "メイン"],
  ["negotiations", "交渉", "⇄", "メイン"],
  ["agreements", "合意", "◇", "メイン"],
  ["peers", "接続相手", "◎", "メイン"],
  ["agentSetup", "代理AI設定", "✦", "エージェント"],
  ["memories", "記憶", "▤", "エージェント"],
  ["clones", "クローン", "◉", "エージェント"],
  ["projects", "プロジェクト", "▱", "開発"],
  ["agents", "外部エージェント", "⌘", "開発"],
  ["tasks", "新規タスク", "+", "開発"],
  ["metrics", "メトリクス", "⌁", "開発"],
];

function PlaceholderPage({ title }: { title: string }) {
  return (
    <main className="page">
      <header className="page-header"><p className="eyebrow">ENISHI</p><h1>{title}</h1></header>
      <section className="empty-state"><div className="empty-icon">◇</div><h2>準備中です</h2><p>この機能は今後のアップデートで利用できるようになります。</p></section>
    </main>
  );
}

export function App() {
  const refresh = useAppStore((state) => state.refresh);
  const [client, setClient] = useState<ApiClient | null>(null);
  const [tab, setTab] = useState<Tab>("home");
  const [focusedSessionId, setFocusedSessionId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const connection = await resolveCoreConnection();
      if (cancelled) return;
      const apiClient = new ApiClient(connection);
      setClient(apiClient);
      await refresh(apiClient);
    })();
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="titlebar-drag" data-tauri-drag-region />
        <div className="brand"><span className="brand-mark">縁</span><div><strong>ENISHI</strong><small>Personal Agent</small></div></div>
        <nav className="sidebar-nav">
        {TABS.map(([key, label, icon, group], index) => (
          <div key={key}>
          {(index === 0 || TABS[index - 1][3] !== group) && <p className="nav-group">{group}</p>}
          <button
            onClick={() => setTab(key)}
            className={`nav-item ${tab === key ? "active" : ""}`}
          >
            <span className="nav-icon">{icon}</span><span>{label}</span>
            {key === "approvals" && <ApprovalBadge />}
          </button>
          </div>
        ))}
        </nav>
        <div className="sidebar-footer"><span className={`status-dot ${client ? "online" : ""}`} /><span>{client ? "Local Core 接続済み" : "接続中…"}</span></div>
      </aside>
      <div className="content-pane">
      {tab === "home" && <HomePage client={client} />}
      {tab === "agentSetup" && (
        <AgentSetupPage client={client} onOpenPeers={() => setTab("peers")} />
      )}
      {tab === "peers" && <PeersPage client={client} />}
      {tab === "negotiations" && <NegotiationsPage client={client} focusedSessionId={focusedSessionId} onOpenApprovals={() => setTab("approvals")} />}
      {tab === "agreements" && <AgreementsPage client={client} />}
      {tab === "approvals" && <ApprovalsPage client={client} onOpenNegotiation={(sessionId) => { setFocusedSessionId(sessionId); setTab("negotiations"); }} onOpenAgreements={() => setTab("agreements")} />}
      {tab === "memories" && <PlaceholderPage title="記憶" />}
      {tab === "metrics" && <MetricsPage client={client} />}
      {tab === "clones" && <PlaceholderPage title="クローン" />}
      {tab === "projects" && <PlaceholderPage title="プロジェクト" />}
      {tab === "agents" && <PlaceholderPage title="外部エージェント" />}
      {tab === "tasks" && <PlaceholderPage title="新規タスク" />}
      </div>
    </div>
  );
}

function ApprovalBadge() {
  const count = useAppStore((state) => state.approvals.filter((item) => item.status === "pending").length);
  return count > 0 ? <span className="nav-badge">{count}</span> : null;
}
