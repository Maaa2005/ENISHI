import { useEffect, useMemo, useState } from "react";
import type { ApiClient } from "../services/api";
import { useAppStore } from "../stores/appStore";
import type { MemoryRead } from "../types";

const typeLabels: Record<string, string> = {
  identity: "本人情報",
  preference: "好み",
  negative_preference: "避けたいこと",
  relationship: "関係性",
  communication: "伝え方",
  skill: "得意なこと",
  policy: "判断方針",
  schedule: "予定",
  project: "プロジェクト",
  decision: "過去の判断",
  environment: "環境",
  episodic: "経験",
};

const titleLabels: Record<string, string> = {
  meeting_schedule: "日程調整の好み",
  relationships: "相手との関係性",
  response_style: "返答スタイル",
  role: "現在の立場",
  coordination: "調整スキル",
  privacy: "プライバシー方針",
  timezone: "タイムゾーン",
};

const sensitivityLabels: Record<string, string> = {
  public: "公開可",
  internal: "端末内",
  private: "非公開",
  restricted: "厳格制限",
  secret: "秘密",
};

function contentSummary(memory: MemoryRead): string {
  if (memory.sensitivity === "secret") return "内容は安全のため画面に表示しません";
  const content = memory.content;
  if (memory.title === "meeting_schedule") {
    const ranges = content.preferred_time_ranges;
    if (Array.isArray(ranges) && ranges[0] && typeof ranges[0] === "object") {
      const range = ranges[0] as Record<string, unknown>;
      return `希望時間帯 ${String(range.start ?? "—")}〜${String(range.end ?? "—")}`;
    }
  }
  if (memory.title === "relationships") {
    const requiresApproval = Object.values(content).some((value) =>
      typeof value === "object" && value !== null && (value as Record<string, unknown>).allow_auto_accept === false,
    );
    return requiresApproval ? "この相手との合意は、必ず本人に確認する" : "信頼関係に応じて代理判断できる";
  }
  if (memory.title === "privacy" && content.share_raw_calendar === false) return "生の予定表は相手へ共有しない";
  if (typeof content.value === "string") return content.value;
  if (typeof content.language === "string") return `${content.language}・${String(content.tone ?? "標準")}`;
  if (typeof content.level === "string") return `習熟度: ${content.level}`;
  return Object.entries(content).map(([key, value]) => `${key}: ${typeof value === "object" ? "設定済み" : String(value)}`).join(" / ") || "設定済み";
}

export function MemoriesPage({ client }: { client: ApiClient | null }) {
  const users = useAppStore((state) => state.users);
  const [memories, setMemories] = useState<MemoryRead[]>([]);
  const [filter, setFilter] = useState("all");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!client || !users[0]) return;
    setError(null);
    void client.listMemories(users[0].id).then(setMemories).catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  }, [client, users]);

  const types = useMemo(() => [...new Set(memories.map((memory) => memory.memory_type))], [memories]);
  const visible = filter === "all" ? memories : memories.filter((memory) => memory.memory_type === filter);
  const privateCount = memories.filter((memory) => ["private", "restricted", "secret"].includes(memory.sensitivity)).length;
  const highConfidence = memories.filter((memory) => memory.confidence >= 0.8).length;
  const sources = new Set(memories.map((memory) => memory.source_type)).size;

  return (
    <main className="page memories-page">
      <header className="page-header"><div><p className="eyebrow">PERSONAL CONTEXT</p><h1>記憶</h1><p className="subtitle">代理AIが判断に使う本人の好み・方針・関係性です。</p></div><span className="privacy-shield">端末内で管理</span></header>
      {error && <p role="alert" className="alert error">記憶を取得できません: {error}</p>}
      <section className="memory-stats"><article><span>有効な記憶</span><strong>{memories.length}</strong></article><article><span>高確信度</span><strong>{highConfidence}</strong></article><article><span>非公開情報</span><strong>{privateCount}</strong></article><article><span>記憶ソース</span><strong>{sources}</strong></article></section>
      <div className="memory-toolbar"><div className="memory-filters"><button className={filter === "all" ? "selected" : ""} onClick={() => setFilter("all")}>すべて</button>{types.map((type) => <button key={type} className={filter === type ? "selected" : ""} onClick={() => setFilter(type)}>{typeLabels[type] ?? type}</button>)}</div><span>{visible.length}件</span></div>
      {!error && memories.length === 0 && <section className="empty-state"><div className="empty-icon">▤</div><h2>記憶はまだありません</h2><p>代理AI設定から記憶ソースを接続すると、ここに判断材料が表示されます。</p></section>}
      <section className="memory-grid">{visible.map((memory) => <article key={memory.id} className="memory-card"><div className="memory-card-top"><span className={`memory-type ${memory.memory_type}`}>{typeLabels[memory.memory_type] ?? memory.memory_type}</span><span className={`sensitivity ${memory.sensitivity}`}>{sensitivityLabels[memory.sensitivity] ?? memory.sensitivity}</span></div><h2>{titleLabels[memory.title] ?? memory.title}</h2><p>{contentSummary(memory)}</p><footer><span>確信度 {Math.round(memory.confidence * 100)}%</span><span>{memory.source_type === "presentation_demo" ? "デモ用プロフィール" : memory.source_type}</span></footer></article>)}</section>
      {memories.length > 0 && <section className="privacy-note"><strong>選択的開示</strong><p>記憶本文は相手へ送りません。交渉時は「この候補で都合が合うか」の判定結果だけを共有します。</p></section>}
    </main>
  );
}
