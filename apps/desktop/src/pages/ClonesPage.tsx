import { useEffect, useMemo, useState } from "react";
import type { ApiClient } from "../services/api";
import { useAppStore } from "../stores/appStore";
import type { CloneRead, MemoryRead } from "../types";

function statusLabel(status: string): string {
  if (status === "active") return "稼働中";
  if (status === "review_required") return "確認待ち";
  if (status === "outdated") return "再学習が必要";
  if (status === "paused") return "停止中";
  return status;
}

function profileSummary(clone: CloneRead): Array<{ label: string; value: string }> {
  const preferred = clone.preference_profile?.meeting_schedule as Record<string, unknown> | undefined;
  const ranges = preferred?.preferred_time_ranges;
  const firstRange = Array.isArray(ranges) && ranges[0] && typeof ranges[0] === "object" ? ranges[0] as Record<string, unknown> : null;
  const relationships = clone.preference_profile?.relationships;
  const relationshipCount = relationships && typeof relationships === "object" ? Object.keys(relationships).length : 0;
  return [
    { label: "役割", value: String(clone.identity_profile?.display_name ?? clone.name) },
    { label: "主な目的", value: String(clone.policy_profile?.purpose ?? "本人の代理") },
    { label: "希望時間", value: firstRange ? `${String(firstRange.start)}〜${String(firstRange.end)}` : "未設定" },
    { label: "関係性ルール", value: relationshipCount ? `${relationshipCount}人分を反映` : "既定ルール" },
  ];
}

export function ClonesPage({ client }: { client: ApiClient | null }) {
  const users = useAppStore((state) => state.users);
  const [clones, setClones] = useState<CloneRead[]>([]);
  const [memories, setMemories] = useState<MemoryRead[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    if (!client || !users[0]) return;
    setError(null);
    try {
      const [cloneRows, memoryRows] = await Promise.all([
        client.listClones(users[0].id),
        client.listMemories(users[0].id),
      ]);
      setClones(cloneRows);
      setMemories(memoryRows);
      if (cloneRows[0]) setSelectedId((current) => current ?? cloneRows[0].id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => {
    void load();
  }, [client, users]);

  const selected = useMemo(() => clones.find((clone) => clone.id === selectedId) ?? clones[0] ?? null, [clones, selectedId]);

  const createDraft = async () => {
    if (!client || !users[0]) return;
    setSaving(true);
    setError(null);
    try {
      const clone = await client.ensureClone(users[0].id, "本人の代理", "codex");
      setSelectedId(clone.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const activateSelected = async () => {
    if (!client || !selected) return;
    setSaving(true);
    setError(null);
    try {
      await client.activateClone(selected.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const score = selected ? Math.round(selected.confidence_score * 100) : 0;
  return (
    <main className="page clones-page">
      <header className="page-header"><div><p className="eyebrow">YOUR REPRESENTATIVE</p><h1>クローン</h1><p className="subtitle">本人の記憶と方針から構成された、委任可能な代理AIです。</p></div>{selected && <span className={`clone-status ${selected.status}`}>{statusLabel(selected.status)}</span>}</header>
      {error && <p role="alert" className="alert error">クローン情報を取得できません: {error}</p>}
      {!error && clones.length === 0 && <section className="empty-state"><div className="empty-icon">◉</div><h2>クローンはまだありません</h2><p>外部脳の記憶と現在の安全設定から、確認用の代理AIを生成します。</p><button className="primary-button" onClick={() => void createDraft()} disabled={saving}>{saving ? "生成中…" : "代理AIを作成"}</button></section>}
      {selected && <div className="clone-layout"><aside className="clone-list"><div className="session-panel-header"><h2>バージョン</h2><span>{clones.length}件</span></div>{clones.map((clone) => <button key={clone.id} onClick={() => setSelectedId(clone.id)} className={`clone-item ${clone.id === selected.id ? "selected" : ""}`}><span className={`session-status ${clone.status === "active" ? "agreed" : clone.status === "outdated" ? "failed" : "waiting"}`} /><div><strong>{clone.name}</strong><p>v{clone.version}・{statusLabel(clone.status)}</p></div></button>)}</aside><section className="clone-detail"><div className="clone-hero"><div className="confidence-ring" style={{ background: `conic-gradient(#3f8058 ${score * 3.6}deg, #e4e5e7 0deg)` }}><div><strong>{score}%</strong><span>確信度</span></div></div><div><p className="eyebrow">ACTIVE PERSONAL AGENT</p><h2>{selected.name}</h2><p>{memories.length}件の記憶と本人の委任方針を使い、必要なときだけ確認を求めます。</p><div className="clone-tags"><span>署名付き通信</span><span>選択的開示</span><span>人間承認ゲート</span></div></div></div><dl className="clone-profile">{profileSummary(selected).map((item) => <div key={item.label}><dt>{item.label}</dt><dd>{item.value}</dd></div>)}</dl><section className="clone-boundary"><div><strong>このクローンに任せられること</strong><p>信頼済みの相手との日程候補の比較・交渉・合意案の作成</p></div><div><strong>本人確認が必要なこと</strong><p>関係性ルールに該当する合意、低確信度の判断、外部へ影響する操作</p></div><div><strong>禁止されていること</strong><p>秘密情報の送信、破壊的操作、本人の許可を越えた確定</p></div></section>{selected.status === "review_required" && <section className="clone-activation"><div><strong>最後に本人確認が必要です</strong><p>上のプロフィールと安全境界を確認したうえで、この代理AIへ委任します。</p></div><button className="primary-button" onClick={() => void activateSelected()} disabled={saving}>{saving ? "有効化中…" : "内容を確認して有効化"}</button></section>}</section></div>}
    </main>
  );
}
