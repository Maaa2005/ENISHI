import { useEffect, useState } from "react";
import type { ApiClient } from "../services/api";
import { useAppStore } from "../stores/appStore";
import type { ProjectRead } from "../types";

const PERMISSION_LABELS: Record<string, string> = {
  read: "読み取り",
  create: "新規作成",
  modify: "変更",
  delete: "削除",
  run_commands: "コマンド実行",
  use_network: "ネットワーク",
  git_commit: "Gitコミット",
  git_push: "Gitプッシュ",
};

export function ProjectsPage({ client }: { client: ApiClient | null }) {
  const user = useAppStore((state) => state.users[0]);
  const [projects, setProjects] = useState<ProjectRead[]>([]);
  const [name, setName] = useState("");
  const [rootPath, setRootPath] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    if (!client || !user) return;
    setError(null);
    try {
      setProjects(await client.listProjects(user.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => { void load(); }, [client, user]);

  const create = async () => {
    if (!client || !user || !name.trim() || !rootPath.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await client.createProject(user.id, name.trim(), rootPath.trim());
      setName("");
      setRootPath("");
      setShowForm(false);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const toggleTrust = async (project: ProjectRead) => {
    if (!client) return;
    setError(null);
    try {
      await client.patchProject(project.id, { trusted: !project.trusted });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <main className="page projects-page">
      <header className="page-header">
        <div><p className="eyebrow">LOCAL WORKSPACES</p><h1>プロジェクト</h1><p className="subtitle">代理AIが参照できる範囲と操作権限を、プロジェクト単位で管理します。</p></div>
        <button className="primary-button header-button" onClick={() => setShowForm((value) => !value)}>プロジェクトを登録</button>
      </header>
      {error && <p role="alert" className="alert error">{error}</p>}
      {showForm && <section className="project-form panel">
        <div><label htmlFor="project-name">表示名</label><input id="project-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="ENISHI" /></div>
        <div><label htmlFor="project-path">ローカルフォルダ</label><input id="project-path" value={rootPath} onChange={(event) => setRootPath(event.target.value)} placeholder="/Users/name/dev/project" /></div>
        <button className="primary-button" disabled={saving || !name.trim() || !rootPath.trim()} onClick={() => void create()}>{saving ? "登録中…" : "この範囲を登録"}</button>
        <p>ホーム全体や存在しないフォルダは登録できません。初期状態では削除・通信・Git送信を禁止します。</p>
      </section>}
      {!error && projects.length === 0 && !showForm && <section className="empty-state"><div className="empty-icon">▱</div><h2>登録済みプロジェクトはありません</h2><p>代理AIに見せる作業範囲を限定して登録できます。</p></section>}
      <div className="project-grid">{projects.map((project) => {
        const allowed = Object.entries(project.permissions).filter(([, value]) => value).map(([key]) => PERMISSION_LABELS[key] ?? key);
        const denied = Object.entries(project.permissions).filter(([, value]) => !value).map(([key]) => PERMISSION_LABELS[key] ?? key);
        return <article className="project-card" key={project.id}>
          <header><div className="project-icon">{project.repository_type === "git" ? "Git" : "Dir"}</div><div><h2>{project.name}</h2><p>{project.root_path}</p></div><span className={`project-trust ${project.trusted ? "trusted" : "restricted"}`}>{project.trusted ? "信頼済み" : "制限中"}</span></header>
          <div className="permission-section"><strong>許可</strong><div>{allowed.map((label) => <span className="permission allowed" key={label}>✓ {label}</span>)}</div></div>
          <div className="permission-section"><strong>要承認・禁止</strong><div>{denied.map((label) => <span className="permission denied" key={label}>— {label}</span>)}</div></div>
          <footer><span>秘密情報はコンテキストへ含めません</span><button onClick={() => void toggleTrust(project)}>{project.trusted ? "信頼を解除" : "信頼する"}</button></footer>
        </article>;
      })}</div>
    </main>
  );
}
