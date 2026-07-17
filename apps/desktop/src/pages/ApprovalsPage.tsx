import { useEffect, useMemo, useState } from "react";
import type { ApiClient } from "../services/api";
import { useAppStore } from "../stores/appStore";
import type { ApprovalRead } from "../types";

type Slot = { start: string; end: string };

function isSlot(value: unknown): value is Slot {
  if (!value || typeof value !== "object") return false;
  const slot = value as Record<string, unknown>;
  return typeof slot.start === "string" && typeof slot.end === "string";
}

function candidateSlots(approval: ApprovalRead): Slot[] {
  const values = Array.isArray(approval.payload.candidate_slots)
    ? approval.payload.candidate_slots.filter(isSlot)
    : [];
  const selected = isSlot(approval.payload.selected_slot) ? approval.payload.selected_slot : null;
  return selected && !values.some((slot) => slot.start === selected.start && slot.end === selected.end)
    ? [selected, ...values]
    : values;
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

function formatDateTime(value: string | undefined): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("ja-JP", {
    month: "long",
    day: "numeric",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function statusLabel(status: string): string {
  if (status === "pending") return "判断待ち";
  if (status === "approved") return "承認済み";
  if (status === "rejected") return "拒否済み";
  if (status === "expired") return "期限切れ";
  return status;
}

function NegotiationDecisionDetails({ approval }: { approval: ApprovalRead }) {
  const reasons = Array.isArray(approval.payload.reason_codes)
    ? approval.payload.reason_codes.filter((value): value is string => typeof value === "string")
    : [];
  const confidence = typeof approval.payload.decision_confidence === "number"
    ? Math.round(approval.payload.decision_confidence * 100)
    : null;
  const slot = approval.payload.selected_slot as { start?: string; end?: string } | undefined;
  return (
    <dl className="approval-facts">
      <div><dt>提案された日時</dt><dd>{formatDateTime(slot?.start)}〜{slot?.end ? new Intl.DateTimeFormat("ja-JP", { hour: "2-digit", minute: "2-digit" }).format(new Date(slot.end)) : "—"}</dd></div>
      <div><dt>代理AIの確信度</dt><dd>{confidence === null ? "—" : `${confidence}%`}</dd></div>
      <div><dt>本人確認の理由</dt><dd>{reasons.map((reason) => reasonLabels[reason] ?? reason).join("、") || "—"}</dd></div>
      <div><dt>承認の有効期限</dt><dd>{formatDateTime(approval.expires_at)}</dd></div>
    </dl>
  );
}

interface ApprovalsPageProps {
  client: ApiClient | null;
  onOpenNegotiation: (sessionId: string) => void;
  onOpenAgreements: () => void;
}

export function ApprovalsPage({ client, onOpenNegotiation, onOpenAgreements }: ApprovalsPageProps) {
  const refreshApp = useAppStore((state) => state.refresh);
  const [approvals, setApprovals] = useState<ApprovalRead[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [processingId, setProcessingId] = useState<string | null>(null);
  const [selectedSlots, setSelectedSlots] = useState<Record<string, Slot>>({});
  const [resolved, setResolved] = useState<{ sessionId: string; action: "approve" | "counter" | "reject" } | null>(null);

  const ordered = useMemo(
    () => [...approvals].sort((a, b) => Number(b.status === "pending") - Number(a.status === "pending")),
    [approvals],
  );
  const pendingCount = approvals.filter((approval) => approval.status === "pending").length;

  const load = async () => {
    if (!client) return;
    setError(null);
    try {
      setApprovals(await client.listApprovals());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => { void load(); }, [client]);
  useEffect(() => {
    if (!client || !error) return;
    const timer = window.setTimeout(() => void load(), 1500);
    return () => window.clearTimeout(timer);
  }, [client, error]);

  const resolve = async (approval: ApprovalRead, action: "approve" | "reject") => {
    if (!client) return;
    setProcessingId(approval.id);
    setError(null);
    try {
      const selected = selectedSlots[approval.id]
        ?? candidateSlots(approval)[0]
        ?? (isSlot(approval.payload.selected_slot) ? approval.payload.selected_slot : undefined);
      if (action === "approve") await client.approveApproval(approval.id, selected);
      else await client.rejectApproval(approval.id);
      await Promise.all([load(), refreshApp(client)]);
      const sessionId = typeof approval.payload.session_id === "string" ? approval.payload.session_id : "";
      const original = isSlot(approval.payload.selected_slot) ? approval.payload.selected_slot : null;
      const isAlternative = action === "approve" && selected && original
        && (selected.start !== original.start || selected.end !== original.end);
      setResolved({ sessionId, action: isAlternative ? "counter" : action });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setProcessingId(null);
    }
  };

  return (
    <main className="page approvals-page">
      <header className="page-header">
        <div><p className="eyebrow">HUMAN CONTROL</p><h1>承認</h1><p className="subtitle">代理AIがあなたを拘束する前に、重要な判断だけを確認します。</p></div>
        <div className={`decision-count ${pendingCount ? "active" : ""}`}><strong>{pendingCount}</strong><span>判断待ち</span></div>
      </header>

      {error && <div role="alert" className="alert error approval-load-error"><span>Local Coreから承認情報を取得できません: {error}</span><button onClick={() => void load()}>再読み込み</button></div>}
      {resolved && (
        <section className={`resolution-banner ${resolved.action === "reject" ? "rejected" : "success"}`}>
          <div><span className="resolution-icon">{resolved.action === "reject" ? "×" : "✓"}</span><div><strong>{resolved.action === "approve" ? "承認しました。AI同士の合意が成立しました" : resolved.action === "counter" ? "選んだ代替候補を相手の代理AIへ提案しました" : "拒否しました。相手の代理AIへ結果を返しました"}</strong><p>{resolved.action === "approve" ? "交渉ログと保存された合意を続けて確認できます。" : resolved.action === "counter" ? "相手の応答を交渉ログで確認できます。" : "交渉ログで拒否結果を確認できます。"}</p></div></div>
          <div className="resolution-actions">
            {resolved.sessionId && <button onClick={() => onOpenNegotiation(resolved.sessionId)}>交渉ログを見る</button>}
            {resolved.action === "approve" && <button className="primary-button" onClick={onOpenAgreements}>成立した合意を見る</button>}
          </div>
        </section>
      )}

      {!error && ordered.length === 0 && <section className="empty-state"><div className="empty-icon">✓</div><h2>判断待ちはありません</h2><p>代理AIは委任範囲内で動作しています。</p></section>}
      <div className="approval-list">
        {ordered.map((approval) => {
          const slots = candidateSlots(approval);
          const selected = selectedSlots[approval.id] ?? slots[0];
          const original = isSlot(approval.payload.selected_slot) ? approval.payload.selected_slot : null;
          const selectingAlternative = Boolean(selected && original && (selected.start !== original.start || selected.end !== original.end));
          return (
          <section key={approval.id} className={`approval-card ${approval.status}`}>
            <div className="approval-card-header">
              <div><p className="eyebrow">NEGOTIATION DECISION</p><h2>{approval.status === "pending" ? "この日程候補を承認しますか？" : "日程候補の判断"}</h2><p>{approval.description}</p></div>
              <span className={`approval-status ${approval.status}`}>{statusLabel(approval.status)}</span>
            </div>
            {approval.action_type === "negotiation_decision"
              ? <NegotiationDecisionDetails approval={approval} />
              : <pre>{JSON.stringify(approval.payload, null, 2)}</pre>}
            {approval.status === "pending" && slots.length > 0 && (
              <fieldset className="approval-slot-options">
                <legend>承認または提案する候補を選択</legend>
                {slots.map((slot) => (
                  <label key={`${slot.start}-${slot.end}`}>
                    <input
                      type="radio"
                      name={`slot-${approval.id}`}
                      checked={selected?.start === slot.start && selected?.end === slot.end}
                      onChange={() => setSelectedSlots((current) => ({ ...current, [approval.id]: slot }))}
                    />
                    <span>{formatDateTime(slot.start)}〜{new Intl.DateTimeFormat("ja-JP", { hour: "2-digit", minute: "2-digit" }).format(new Date(slot.end))}</span>
                    {original?.start === slot.start && original.end === slot.end && <small>代理AIの第一候補</small>}
                  </label>
                ))}
              </fieldset>
            )}
            {approval.status === "pending" && (
              <div className="approval-actions">
                <button onClick={() => void resolve(approval, "reject")} disabled={processingId === approval.id}>拒否する</button>
                <button className="primary-button" onClick={() => void resolve(approval, "approve")} disabled={processingId === approval.id}>{processingId === approval.id ? "処理中…" : selectingAlternative ? "この代替案を相手へ提案" : "この候補を承認"}</button>
              </div>
            )}
          </section>
        );})}
      </div>
    </main>
  );
}
