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

const reasonLabels: Record<string, string> = {
  schedule_negotiation_not_delegated: "日程交渉を代理AIへ委任していません",
  clone_confidence_below_threshold: "代理AIの判断確信度が基準を下回っています",
  meeting_auto_accept_disabled: "日程候補の自動承認が無効です",
  meeting_outside_preferred_time: "希望時間帯から外れています",
  meeting_time_avoided: "避けたい時間帯に含まれています",
  relationship_requires_approval: "この相手との交渉は本人確認が必要です",
  common_slot_within_delegation: "委任範囲内で共通候補が見つかりました",
};

function NegotiationDecisionDetails({ approval }: { approval: ApprovalRead }) {
  const reasons = Array.isArray(approval.payload.reason_codes)
    ? approval.payload.reason_codes.filter((value): value is string => typeof value === "string")
    : [];
  const confidence = typeof approval.payload.decision_confidence === "number"
    ? Math.round(approval.payload.decision_confidence * 100)
    : null;
  const slot = approval.payload.selected_slot as { start?: string; end?: string } | undefined;
  return (
    <dl className="decision-facts">
      <div><dt>提案された判断</dt><dd>この日程候補を承認する</dd></div>
      <div><dt>候補日時</dt><dd>{slot?.start ?? "—"} 〜 {slot?.end ?? "—"}</dd></div>
      <div><dt>代理AIの確信度</dt><dd>{confidence === null ? "—" : `${confidence}%`}</dd></div>
      <div><dt>本人確認が必要な理由</dt><dd>{reasons.map((reason) => reasonLabels[reason] ?? reason).join("、") || "—"}</dd></div>
    </dl>
  );
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
            {approval.action_type === "negotiation_decision"
              ? <NegotiationDecisionDetails approval={approval} />
              : <pre style={{ background: "#f6f6f6", padding: "0.75rem", overflowX: "auto" }}>{JSON.stringify(approval.payload, null, 2)}</pre>}
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
