import { useEffect, useMemo, useState } from "react";
import type { ApiClient } from "../services/api";
import type { AgreementRead } from "../types";

function intentLabel(intent: string): string {
  if (intent === "meeting.schedule") return "日程調整";
  if (intent === "task.request") return "仕事の依頼";
  return intent;
}

function statusLabel(status: string): string {
  if (status === "active") return "有効";
  if (status === "fulfilled") return "完了";
  if (status === "cancelled") return "取り消し";
  return status;
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("ja-JP", { month: "long", day: "numeric", weekday: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function selectedSlot(agreement: AgreementRead): { start: string; end: string } | null {
  const value = agreement.agreed_payload.selected_slot;
  if (!value || typeof value !== "object") return null;
  const slot = value as Record<string, unknown>;
  return typeof slot.start === "string" && typeof slot.end === "string" ? { start: slot.start, end: slot.end } : null;
}

export function AgreementsPage({ client }: { client: ApiClient | null }) {
  const [agreements, setAgreements] = useState<AgreementRead[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const selected = useMemo(() => agreements.find((agreement) => agreement.id === selectedId) ?? agreements[0] ?? null, [agreements, selectedId]);

  const load = async () => {
    if (!client) return;
    setError(null);
    try {
      const rows = await client.listAgreements();
      setAgreements(rows);
      if (!selectedId && rows[0]) setSelectedId(rows[0].id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => { void load(); }, [client]);

  const changeStatus = async (next: "fulfilled" | "cancelled") => {
    if (!client || !selected) return;
    await client.patchAgreementStatus(selected.id, next);
    await load();
  };

  const slot = selected ? selectedSlot(selected) : null;
  return (
    <main className="page agreements-page">
      <header className="page-header"><div><p className="eyebrow">SETTLED OUTCOMES</p><h1>合意</h1><p className="subtitle">本人の承認を経て、AI同士が確定した結果です。</p></div><div className="decision-count"><strong>{agreements.length}</strong><span>成立済み</span></div></header>
      {error && <p role="alert" className="alert error">合意情報を取得できません: {error}</p>}
      {!error && agreements.length === 0 && <section className="empty-state"><div className="empty-icon">◇</div><h2>成立した合意はありません</h2><p>承認された交渉結果がここに保存されます。</p></section>}
      {agreements.length > 0 && <div className="agreement-layout">
        <aside className="agreement-list"><div className="session-panel-header"><h2>合意一覧</h2><span>{agreements.length}件</span></div>{agreements.map((agreement) => {
          const itemSlot = selectedSlot(agreement);
          return <button key={agreement.id} onClick={() => setSelectedId(agreement.id)} className={`agreement-item ${agreement.id === selected?.id ? "selected" : ""}`}><span className={`session-status ${agreement.status === "cancelled" ? "failed" : "agreed"}`} /><div><strong>{intentLabel(agreement.intent)}</strong><p>{itemSlot ? formatDateTime(itemSlot.start) : formatDateTime(agreement.agreed_at)}</p></div><span className="pill success">{statusLabel(agreement.status)}</span></button>;
        })}</aside>
        {selected && <section className="agreement-detail">
          <div className="agreement-success"><span>✓</span><div><p className="eyebrow">AGREEMENT REACHED</p><h2>AI同士の合意が成立しました</h2><p>本人の承認を反映し、双方のノードに同じ結果が保存されています。</p></div></div>
          {slot && <div className="agreed-slot"><span>確定日時</span><strong>{formatDateTime(slot.start)}</strong><small>終了 {new Intl.DateTimeFormat("ja-JP", { hour: "2-digit", minute: "2-digit" }).format(new Date(slot.end))}</small></div>}
          <dl className="agreement-facts"><div><dt>種類</dt><dd>{intentLabel(selected.intent)}</dd></div><div><dt>状態</dt><dd>{statusLabel(selected.status)}</dd></div><div><dt>合意日時</dt><dd>{formatDateTime(selected.agreed_at)}</dd></div><div><dt>プロトコル</dt><dd>AUN Protocol 0.1</dd></div></dl>
          <div className="agreement-actions"><button onClick={() => void changeStatus("cancelled")} disabled={selected.status !== "active"}>合意を取り消す</button><button className="primary-button" onClick={() => void changeStatus("fulfilled")} disabled={selected.status !== "active"}>完了として記録</button></div>
        </section>}
      </div>}
    </main>
  );
}
