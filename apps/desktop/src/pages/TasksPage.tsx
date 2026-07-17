import { useEffect, useMemo, useState } from "react";
import type { ApiClient } from "../services/api";
import { useAppStore } from "../stores/appStore";
import type { ProjectRead, TaskRead } from "../types";

function statusLabel(status: string): string {
  if (status === "waiting_approval") return "承認待ち";
  if (status === "queued") return "待機中";
  if (status === "running") return "実行中";
  if (status === "completed") return "完了";
  if (status === "failed") return "失敗";
  if (status === "cancelled") return "取消済み";
  if (status === "expired") return "期限切れ";
  return status;
}

function providerLabel(provider: string): string {
  if (provider === "claude_code") return "Claude Code";
  if (provider === "codex") return "Codex";
  return "安全なデモ実行";
}

export function TasksPage({ client, onOpenApprovals }: { client: ApiClient | null; onOpenApprovals: () => void }) {
  const user = useAppStore((state) => state.users[0]);
  const clones = useAppStore((state) => state.clones);
  const activeClone = clones.find((clone) => clone.status === "active") ?? null;
  const [tasks, setTasks] = useState<TaskRead[]>([]);
  const [projects, setProjects] = useState<ProjectRead[]>([]);
  const [description, setDescription] = useState("");
  const [projectId, setProjectId] = useState("");
  const [provider, setProvider] = useState<"mock" | "codex" | "claude_code">("mock");
  const [creating, setCreating] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const selected = useMemo(() => tasks.find((task) => task.id === selectedId) ?? tasks[0] ?? null, [tasks, selectedId]);

  const load = async () => {
    if (!client || !user) return;
    try {
      const [taskRows, projectRows] = await Promise.all([client.listTasks(user.id), client.listProjects(user.id)]);
      setTasks(taskRows);
      setProjects(projectRows);
      if (taskRows[0]) setSelectedId((current) => current ?? taskRows[0].id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => { void load(); }, [client, user]);
  useEffect(() => {
    if (!client || !user || !tasks.some((task) => ["queued", "running"].includes(task.status))) return;
    const timer = window.setInterval(() => void load(), 700);
    return () => window.clearInterval(timer);
  }, [client, user, tasks]);

  const create = async () => {
    if (!client || !user || !activeClone || !description.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const task = await client.createTask({
        user_id: user.id,
        clone_id: activeClone.id,
        provider,
        description: description.trim(),
        ...(projectId ? { project_id: projectId } : {}),
        requested_operations: [],
      });
      setDescription("");
      setSelectedId(task.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCreating(false);
    }
  };

  return (
    <main className="page tasks-page">
      <header className="page-header"><div><p className="eyebrow">DELEGATED WORK</p><h1>AIタスク</h1><p className="subtitle">クローンが必要な情報だけをまとめ、選んだエージェントへ安全に委任します。</p></div><div className="decision-count"><strong>{tasks.length}</strong><span>実行履歴</span></div></header>
      {error && <p role="alert" className="alert error">{error}</p>}
      <section className="task-compose panel">
        <div><label htmlFor="task-description">クローンへ依頼</label><textarea id="task-description" rows={3} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="このプロジェクトのテスト結果を要約して" /></div>
        <div className="task-options"><label>対象プロジェクト<select value={projectId} onChange={(event) => setProjectId(event.target.value)}><option value="">プロジェクト指定なし</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label><label>実行エージェント<select value={provider} onChange={(event) => setProvider(event.target.value as typeof provider)}><option value="mock">安全なデモ実行</option><option value="codex">Codex</option><option value="claude_code">Claude Code</option></select></label><button className="primary-button" disabled={creating || !activeClone || !description.trim()} onClick={() => void create()}>{creating ? "委任中…" : "クローンに委任"}</button></div>
        <p className="task-safety">削除・設定変更・通信・Git操作を伴う場合は、実行前に承認画面で停止します。</p>
      </section>
      {!activeClone && <p role="alert" className="alert error">稼働中のクローンがありません。先に代理AI設定を完了してください。</p>}
      {tasks.length === 0 && <section className="empty-state compact-task-empty"><div className="empty-icon">+</div><h2>タスク履歴はまだありません</h2><p>上の入力欄からクローンへ仕事を委任できます。</p></section>}
      {tasks.length > 0 && <div className="task-layout"><aside className="task-list"><div className="session-panel-header"><h2>履歴</h2><span>{tasks.length}件</span></div>{tasks.map((task) => <button key={task.id} onClick={() => setSelectedId(task.id)} className={`task-item ${task.id === selected?.id ? "selected" : ""}`}><span className={`task-status-dot ${task.status}`} /><div><strong>{task.description}</strong><p>{providerLabel(task.provider)}・{statusLabel(task.status)}</p></div></button>)}</aside>{selected && <section className="task-detail"><header><div><p className="eyebrow">TASK DETAIL</p><h2>{selected.description}</h2></div><span className={`approval-status ${selected.status}`}>{statusLabel(selected.status)}</span></header><dl className="task-facts"><div><dt>実行エージェント</dt><dd>{providerLabel(selected.provider)}</dd></div><div><dt>コンテキスト</dt><dd>{selected.context_package_id ? "必要情報だけを生成済み" : "準備中"}</dd></div><div><dt>開始</dt><dd>{new Intl.DateTimeFormat("ja-JP", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(selected.created_at))}</dd></div></dl>{selected.status === "waiting_approval" && <button className="primary-button" onClick={onOpenApprovals}>承認内容を確認</button>}{selected.output_lines.length > 0 && <div className="task-output"><strong>実行ログ</strong><pre>{selected.output_lines.join("\n")}</pre></div>}{selected.failure_message && <p className="alert error">{selected.failure_message}</p>}</section>}</div>}
    </main>
  );
}
