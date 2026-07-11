import { useEffect, useState } from "react";
import { AgreementsPage } from "./pages/AgreementsPage";
import { ApprovalsPage } from "./pages/ApprovalsPage";
import { HomePage } from "./pages/HomePage";
import { MetricsPage } from "./pages/MetricsPage";
import { NegotiationsPage } from "./pages/NegotiationsPage";
import { PeersPage } from "./pages/PeersPage";
import { ApiClient } from "./services/api";
import { resolveCoreConnection } from "./services/backend";
import { useAppStore } from "./stores/appStore";

type Tab =
  | "home"
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

const TABS: Array<[Tab, string]> = [
  ["home", "ホーム"],
  ["peers", "Peers"],
  ["negotiations", "交渉"],
  ["agreements", "合意"],
  ["approvals", "承認"],
  ["memories", "記憶"],
  ["metrics", "メトリクス"],
  ["clones", "クローン"],
  ["projects", "プロジェクト"],
  ["agents", "エージェント"],
  ["tasks", "新規タスク"],
];

function PlaceholderPage({ title }: { title: string }) {
  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "2rem", maxWidth: 720 }}>
      <h1>{title}</h1>
      <p>既存の拡張APIを維持し、中核MVP完了後に画面を拡張します。</p>
    </main>
  );
}

export function App() {
  const refresh = useAppStore((state) => state.refresh);
  const [client, setClient] = useState<ApiClient | null>(null);
  const [tab, setTab] = useState<Tab>("home");

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
    <div>
      <nav
        style={{
          display: "flex",
          gap: "0.5rem",
          padding: "0.75rem 2rem",
          borderBottom: "1px solid #ddd",
          fontFamily: "system-ui, sans-serif",
        }}
      >
        {TABS.map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            style={{
              padding: "0.4rem 0.9rem",
              borderRadius: 4,
              border: "1px solid #ccc",
              background: tab === key ? "#eef" : "#fff",
              fontWeight: tab === key ? 600 : 400,
              cursor: "pointer",
            }}
          >
            {label}
          </button>
        ))}
      </nav>
      {tab === "home" && <HomePage />}
      {tab === "peers" && <PeersPage client={client} />}
      {tab === "negotiations" && <NegotiationsPage client={client} />}
      {tab === "agreements" && <AgreementsPage client={client} />}
      {tab === "approvals" && <ApprovalsPage client={client} />}
      {tab === "memories" && <PlaceholderPage title="記憶" />}
      {tab === "metrics" && <MetricsPage client={client} />}
      {tab === "clones" && <PlaceholderPage title="クローン" />}
      {tab === "projects" && <PlaceholderPage title="プロジェクト" />}
      {tab === "agents" && <PlaceholderPage title="外部エージェント" />}
      {tab === "tasks" && <PlaceholderPage title="新規タスク" />}
    </div>
  );
}
