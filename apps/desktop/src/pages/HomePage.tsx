import { useAppStore } from "../stores/appStore";

function providerLabel(provider: string): string {
  return provider === "codex" ? "Codex" : provider === "claude_code" ? "Claude Code" : provider;
}

export function HomePage() {
  const { loading, error, health, environment, clones, peers, negotiations, approvals, agreements, metrics } =
    useAppStore();

  const activePeers = peers.filter((peer) => peer.status === "trusted").length;
  const activeNegotiations = negotiations.filter((session) =>
    ["open", "waiting_approval"].includes(session.status),
  ).length;
  const pendingApprovals = approvals.filter((approval) => approval.status === "pending").length;
  const emailTokens = metrics?.methods.find((method) => method.method === "email")?.total_tokens ?? 0;
  const structuredTokens =
    metrics?.methods.find((method) => method.method === "structured")?.total_tokens ?? 0;
  const savedTokens = emailTokens - structuredTokens;

  const rows: Array<[string, string]> = [
    ["macOS", environment ? `利用可能（${environment.macos_version} / ${environment.architecture}）` : "確認中"],
    ["Local Core", health ? `接続済み（v${health.version}）` : error ? "未接続" : "接続中"],
    ["データベース", health?.database_connected ? "接続済み" : "未接続"],
  ];

  for (const provider of environment?.providers ?? []) {
    rows.push([
      providerLabel(provider.provider),
      provider.installed ? `検出（${provider.version ?? "バージョン不明"}）` : "未検出",
    ]);
  }

  rows.push([
    "本人クローン",
    clones.length > 0 ? `${clones[0].name}（${clones[0].status}）` : "未作成",
  ]);
  rows.push(["接続ピア", `${activePeers} trusted / ${peers.length} total`]);
  rows.push(["進行中交渉", `${activeNegotiations} 件`]);
  rows.push(["未処理承認", `${pendingApprovals} 件`]);
  rows.push(["合意", `${agreements.length} 件`]);
  rows.push(["削減トークン", `${Math.max(0, savedTokens)} tokens`]);

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "2rem", maxWidth: 640 }}>
      <h1>TwinLink Desktop</h1>
      {error && (
        <p role="alert" style={{ color: "#c0392b" }}>
          Local Coreへ接続できません: {error}
        </p>
      )}
      <dl>
        {rows.map(([label, value]) => (
          <div key={label} style={{ display: "flex", gap: "1rem", padding: "0.25rem 0" }}>
            <dt style={{ width: 160, fontWeight: 600 }}>{label}</dt>
            <dd style={{ margin: 0 }}>{loading && !health ? "…" : value}</dd>
          </div>
        ))}
      </dl>
    </main>
  );
}
