import { useEffect, useState } from "react";
import type { ApiClient } from "../services/api";
import type { ApprovalRead } from "../types";

const sectionStyle: React.CSSProperties = {
  border: "1px solid #ddd",
  borderRadius: 8,
  padding: "1rem",
};

function statusColor(status: string): string {
  if (status === "pending") return "#8a5a00";
  if (status === "approved") return "#1f7a1f";
  if (status === "rejected" || status === "expired") return "#b3261e";
  return "#555";
}

export function ApprovalsPage({ client }: { client: ApiClient | null }) {
  const [approvals, setApprovals] = useState<ApprovalRead[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    if (!client) return;
    setError(null);
    try {
      setApprovals(await client.listApprovals());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => {
    void load();
  }, [client]);

  const resolve = async (approval: ApprovalRead, action: "approve" | "reject") => {
    if (!client) return;
    if (action === "approve") await client.approveApproval(approval.id);
    else await client.rejectApproval(approval.id);
    await load();
  };

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "2rem", maxWidth: 960 }}>
      <h1>承認</h1>
      {error && <p style={{ color: "#c0392b" }}>{error}</p>}
      {approvals.length === 0 && <p>承認待ちはありません</p>}
      <div style={{ display: "grid", gap: "1rem" }}>
        {approvals.map((approval) => (
          <section key={approval.id} style={sectionStyle}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem" }}>
              <div>
                <h3 style={{ margin: 0 }}>{approval.action_type}</h3>
                <p style={{ margin: "0.25rem 0" }}>{approval.description}</p>
                <p style={{ margin: 0, color: "#555" }}>
                  level {approval.level} / expires_at {approval.expires_at}
                </p>
              </div>
              <strong style={{ color: statusColor(approval.status) }}>{approval.status}</strong>
            </div>
            <pre style={{ background: "#f6f6f6", padding: "0.75rem", overflowX: "auto" }}>
              {JSON.stringify(approval.payload, null, 2)}
            </pre>
            {approval.status === "pending" && (
              <div style={{ display: "flex", gap: "0.5rem" }}>
                <button onClick={() => resolve(approval, "approve")}>承認</button>
                <button onClick={() => resolve(approval, "reject")}>拒否</button>
              </div>
            )}
          </section>
        ))}
      </div>
    </main>
  );
}
