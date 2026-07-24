import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { useDeepLinkInvite } from "./hooks/useDeepLinkInvite";
import { ApiClient } from "./services/api";
import { resolveCoreConnection, waitForCore } from "./services/backend";
import { useAppStore } from "./stores/appStore";
import "./styles.css";

const AgreementsPage = lazy(() => import("./pages/AgreementsPage").then((module) => ({ default: module.AgreementsPage })));
const AgentSetupPage = lazy(() => import("./pages/AgentSetupPage").then((module) => ({ default: module.AgentSetupPage })));
const ApprovalsPage = lazy(() => import("./pages/ApprovalsPage").then((module) => ({ default: module.ApprovalsPage })));
const AuditPage = lazy(() => import("./pages/AuditPage").then((module) => ({ default: module.AuditPage })));
const ClonesPage = lazy(() => import("./pages/ClonesPage").then((module) => ({ default: module.ClonesPage })));
const HomePage = lazy(() => import("./pages/HomePage").then((module) => ({ default: module.HomePage })));
const MemoriesPage = lazy(() => import("./pages/MemoriesPage").then((module) => ({ default: module.MemoriesPage })));
const MetricsPage = lazy(() => import("./pages/MetricsPage").then((module) => ({ default: module.MetricsPage })));
const NegotiationsPage = lazy(() => import("./pages/NegotiationsPage").then((module) => ({ default: module.NegotiationsPage })));
const PeersPage = lazy(() => import("./pages/PeersPage").then((module) => ({ default: module.PeersPage })));
const ProjectsPage = lazy(() => import("./pages/ProjectsPage").then((module) => ({ default: module.ProjectsPage })));
const TasksPage = lazy(() => import("./pages/TasksPage").then((module) => ({ default: module.TasksPage })));

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
  | "audit"
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
  ["audit", "監査ログ", "◷", "エージェント"],
  ["tasks", "AIタスク", "+", "開発"],
  ["metrics", "メトリクス", "⌁", "開発"],
];

export function App() {
  const refresh = useAppStore((state) => state.refresh);
  const [client, setClient] = useState<ApiClient | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [reconnectKey, setReconnectKey] = useState(0);
  const [tab, setTab] = useState<Tab>("home");
  const [focusedSessionId, setFocusedSessionId] = useState<string | null>(null);
  const [pendingInvite, setPendingInvite] = useState<string | null>(null);
  const acceptInvite = useCallback((invite: string) => {
    setPendingInvite(invite);
    setTab("peers");
  }, []);
  const deepLinkError = useDeepLinkInvite(acceptInvite);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setClient(null);
      setConnectionError(null);
      try {
        const connection = await resolveCoreConnection();
        const apiClient = new ApiClient(connection);
        await waitForCore(apiClient);
        if (cancelled) return;
        setClient(apiClient);
        await refresh(apiClient);
      } catch (error) {
        if (!cancelled) setConnectionError(error instanceof Error ? error.message : String(error));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refresh, reconnectKey]);

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
        <div className="sidebar-footer"><span className={`status-dot ${client ? "online" : connectionError ? "offline" : ""}`} /><span>{client ? "Local Core 接続済み" : connectionError ? "接続エラー" : "Local Core 起動中…"}</span></div>
      </aside>
      <div className="content-pane">
      {connectionError && <section className="connection-error" role="alert"><div><strong>Local Coreへ接続できません</strong><p>{connectionError}</p></div><button onClick={() => setReconnectKey((value) => value + 1)}>再接続</button></section>}
      {deepLinkError && <section className="connection-error" role="alert"><div><strong>招待リンクエラー</strong><p>{deepLinkError}</p></div></section>}
      <Suspense fallback={<section className="loading-state" aria-live="polite">画面を読み込んでいます…</section>}>
      {tab === "home" && <HomePage client={client} />}
      {tab === "agentSetup" && (
        <AgentSetupPage client={client} onOpenPeers={() => setTab("peers")} />
      )}
      {tab === "peers" && (
        <PeersPage
          client={client}
          incomingInvite={pendingInvite}
          onInviteConsumed={() => setPendingInvite(null)}
        />
      )}
      {tab === "negotiations" && <NegotiationsPage client={client} focusedSessionId={focusedSessionId} onOpenApprovals={() => setTab("approvals")} />}
      {tab === "agreements" && <AgreementsPage client={client} />}
      {tab === "approvals" && <ApprovalsPage client={client} onOpenNegotiation={(sessionId) => { setFocusedSessionId(sessionId); setTab("negotiations"); }} onOpenAgreements={() => setTab("agreements")} />}
      {tab === "memories" && <MemoriesPage client={client} />}
      {tab === "metrics" && <MetricsPage client={client} />}
      {tab === "clones" && <ClonesPage client={client} />}
      {tab === "projects" && <ProjectsPage client={client} />}
      {tab === "audit" && <AuditPage client={client} />}
      {tab === "tasks" && <TasksPage client={client} onOpenApprovals={() => setTab("approvals")} />}
      </Suspense>
      </div>
    </div>
  );
}

function ApprovalBadge() {
  const count = useAppStore((state) => state.approvals.filter((item) => item.status === "pending").length);
  return count > 0 ? <span className="nav-badge">{count}</span> : null;
}
