import { useEffect, useState } from "react";
import type { ApiClient } from "../services/api";
import type {
  DefaultDisclosurePolicyRead,
  MemoryBackendRead,
  MemorySourceSettingRead,
  MemorySourceDiscoveryRead,
  MeetingPreferencesRead,
  PolicyRead,
  ProviderStatusDetail,
  UserRead,
  TimeRange,
} from "../types";

const memoryTypes = ["identity", "preference", "skill", "project", "decision", "policy", "schedule"];
const sensitivities = ["public", "internal", "private"];
const delegationLabels: Record<string, string> = {
  schedule_negotiation: "日程調整",
  task_negotiation: "仕事の提案・条件交渉",
  coding_task: "コーディング依頼",
  external_service_operation: "外部サービス操作",
};
const approvalLabels: Record<string, string> = {
  git_push: "Git Push",
  file_delete: "ファイル削除",
  external_publish: "外部公開",
  high_value: "高額案件",
};

const pageStyle: React.CSSProperties = {
  fontFamily: "system-ui, sans-serif",
  padding: "2rem",
  maxWidth: 1180,
};
const sectionStyle: React.CSSProperties = {
  border: "1px solid #ddd",
  borderRadius: 8,
  padding: "1rem",
  background: "#fff",
};
const gridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
  gap: "1rem",
};

function Status({ children }: { children: React.ReactNode }) {
  return (
    <span style={{ border: "1px solid #ccc", borderRadius: 4, padding: "0.15rem 0.4rem" }}>
      {children}
    </span>
  );
}

function patchRule(policy: PolicyRead | null, key: string, value: boolean): Record<string, boolean> {
  return { ...(policy?.rules ?? {}), [key]: value };
}

function TimeRangeEditor({
  label,
  ranges,
  onChange,
}: {
  label: string;
  ranges: TimeRange[];
  onChange: (ranges: TimeRange[]) => void;
}) {
  return (
    <div style={{ marginTop: "0.8rem" }}>
      <strong>{label}</strong>
      {ranges.map((range, index) => (
        <div key={`${index}-${range.start}-${range.end}`} style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
          <input type="time" value={range.start} onChange={(event) => onChange(ranges.map((item, itemIndex) => itemIndex === index ? { ...item, start: event.target.value } : item))} />
          <span>〜</span>
          <input type="time" value={range.end} onChange={(event) => onChange(ranges.map((item, itemIndex) => itemIndex === index ? { ...item, end: event.target.value } : item))} />
          <button onClick={() => onChange(ranges.filter((_, itemIndex) => itemIndex !== index))}>削除</button>
        </div>
      ))}
      <button onClick={() => onChange([...ranges, { start: "09:00", end: "10:00" }])}>時間帯を追加</button>
    </div>
  );
}

export function AgentSetupPage({
  client,
  onOpenPeers,
}: {
  client: ApiClient | null;
  onOpenPeers: () => void;
}) {
  const [user, setUser] = useState<UserRead | null>(null);
  const [sources, setSources] = useState<MemorySourceSettingRead[]>([]);
  const [memoryBackend, setMemoryBackend] = useState<MemoryBackendRead | null>(null);
  const [discoveredSources, setDiscoveredSources] = useState<MemorySourceDiscoveryRead[]>([]);
  const [disclosure, setDisclosure] = useState<DefaultDisclosurePolicyRead | null>(null);
  const [delegation, setDelegation] = useState<PolicyRead | null>(null);
  const [approvalRules, setApprovalRules] = useState<PolicyRead | null>(null);
  const [providers, setProviders] = useState<ProviderStatusDetail[]>([]);
  const [meetingPreferences, setMeetingPreferences] = useState<MeetingPreferencesRead | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);

  const load = async () => {
    if (!client) return;
    setError(null);
    try {
      const [loadedUsers, loadedSources, loadedDiscovered, loadedDisclosure, loadedProviders] = await Promise.all([
        client.listUsers(),
        client.listMemorySources(),
        client.discoverMemorySources(),
        client.getDefaultDisclosure(),
        client.listProviders(),
      ]);
      const currentUser = loadedUsers[0] ?? null;
      setUser(currentUser);
      setSources(loadedSources);
      setDiscoveredSources(loadedDiscovered);
      setDisclosure(loadedDisclosure);
      setProviders(loadedProviders);
      if (currentUser) {
        const [loadedDelegation, loadedApprovalRules, loadedMemoryBackend] = await Promise.all([
          client.getDelegationPolicy(currentUser.id),
          client.getApprovalRulesPolicy(currentUser.id),
          client.getMemoryBackend(currentUser.id),
        ]);
        setDelegation(loadedDelegation);
        setApprovalRules(loadedApprovalRules);
        setMemoryBackend(loadedMemoryBackend);
        try {
          setMeetingPreferences(await client.getMeetingPreferences(currentUser.id));
        } catch {
          setMeetingPreferences(null);
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => {
    void load();
  }, [client]);

  const saveUser = async () => {
    if (!client || !user) return;
    setUser(
      await client.updateUser(user.id, {
        display_name: user.display_name,
        nickname: user.nickname,
        timezone: user.timezone,
        language: user.language,
      }),
    );
  };

  const saveSource = async (source: MemorySourceSettingRead) => {
    if (!client) return;
    setSources(
      await client.putMemorySources([
        { source: source.source, enabled: source.enabled, scope: source.scope },
      ]),
    );
  };

  const syncSource = async (source: MemorySourceSettingRead) => {
    if (!client || !user) return;
    setError(null);
    try {
      const result = await client.syncMemorySource(source.source, user.id);
      setSyncMessage(`${source.source}: 新規${result.created}件・更新${result.updated}件・削除反映${result.deleted}件`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const migrateMemoryBackend = async () => {
    if (!client || !user) return;
    setError(null);
    try {
      const result = await client.migrateMemoryBackend(user.id);
      setSyncMessage(`正本へ${result.migrated}件移行・保留${result.pending}件・失敗${result.failed}件`);
      setMemoryBackend(await client.getMemoryBackend(user.id));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const connectDiscoveredSource = async (source: MemorySourceDiscoveryRead) => {
    if (!client) return;
    setSources(await client.putMemorySources([{ source: source.source, enabled: true, scope: source.path }]));
  };

  const saveDisclosure = async () => {
    if (!client || !disclosure) return;
    setDisclosure(
      await client.putDefaultDisclosure({
        allowed_memory_types: disclosure.allowed_memory_types,
        max_sensitivity: disclosure.max_sensitivity,
        share_schedule: disclosure.share_schedule,
        share_skills: disclosure.share_skills,
        extra: disclosure.extra,
      }),
    );
  };

  const saveDelegation = async (rules: Record<string, boolean>) => {
    if (!client || !user) return;
    setDelegation(await client.putDelegationPolicy(user.id, rules));
  };

  const saveApprovalRules = async (rules: Record<string, boolean>) => {
    if (!client || !user) return;
    setApprovalRules(await client.putApprovalRulesPolicy(user.id, rules));
  };

  const saveMeetingPreferences = async () => {
    if (!client || !user || !meetingPreferences) return;
    setMeetingPreferences(await client.putMeetingPreferences(
      user.id,
      meetingPreferences.preferred_time_ranges,
      meetingPreferences.avoid_time_ranges,
    ));
  };

  const allowed = new Set(disclosure?.allowed_memory_types ?? []);

  return (
    <main style={pageStyle}>
      <h1>あなたの代理AIを育てる</h1>
      {error && <p style={{ color: "#c0392b" }}>{error}</p>}
      {!user && <p>まずユーザーを作成してください。</p>}
      {user && (
        <div style={gridStyle}>
          <section style={sectionStyle}>
            <h3 style={{ marginTop: 0 }}>基本プロフィール</h3>
            <p>
              <Status>現在: {user.display_name}</Status>{" "}
              <Status>呼び名: {user.nickname || "未設定"}</Status>
            </p>
            <label>
              名前
              <input
                value={user.display_name}
                onChange={(e) => setUser({ ...user, display_name: e.target.value })}
              />
            </label>
            <label>
              呼び名
              <input
                value={user.nickname ?? ""}
                onChange={(e) => setUser({ ...user, nickname: e.target.value || null })}
              />
            </label>
            <label>
              使用言語
              <input value={user.language} onChange={(e) => setUser({ ...user, language: e.target.value })} />
            </label>
            <label>
              タイムゾーン
              <input value={user.timezone} onChange={(e) => setUser({ ...user, timezone: e.target.value })} />
            </label>
            <button onClick={saveUser}>保存</button>
          </section>

          <section style={sectionStyle}>
            <h3 style={{ marginTop: 0 }}>記憶ソース</h3>
            <p>外部脳が見つかればそれを正本にし、未接続の場合だけENISHI内蔵メモリを正本にします。</p>
            {memoryBackend && (
              <div style={{ border: "1px solid #ddd", borderRadius: 6, padding: "0.7rem", marginBottom: "0.7rem" }}>
                <strong>現在の正本: {memoryBackend.primary_source === "memories" ? "ENISHI内蔵" : memoryBackend.primary_source}</strong>
                <p style={{ margin: "0.35rem 0" }}>
                  <Status>{memoryBackend.status}</Status>{" "}
                  {memoryBackend.detected_automatically && <Status>自動検出</Status>}{" "}
                  {memoryBackend.pending_count > 0 && <Status>同期待ち {memoryBackend.pending_count}件</Status>}
                </p>
                {memoryBackend.primary_scope && <small>{memoryBackend.primary_scope}</small>}
                {memoryBackend.status === "migrating" && (
                  <div><button onClick={() => void migrateMemoryBackend()}>既存記憶を正本へ移行</button></div>
                )}
                {memoryBackend.status === "external_unavailable" && (
                  <p>外部脳は一時的に利用できません。新しい記憶は復旧までENISHI内で保留します。</p>
                )}
              </div>
            )}
            {discoveredSources.map((source) => (
              <button key={source.path} onClick={() => void connectDiscoveredSource(source)}>
                検出した {source.label} を接続
              </button>
            ))}
            {syncMessage && <p>{syncMessage}</p>}
            {sources.map((source) => (
              <div key={source.source} style={{ borderTop: "1px solid #eee", padding: "0.6rem 0" }}>
                <strong>{source.source}</strong>{" "}
                <Status>{source.connected ? "接続済み" : "未接続"}</Status>{" "}
                <Status>{source.enabled ? "利用中" : "未使用"}</Status>
                <div>
                  <label>
                    <input
                      type="checkbox"
                      checked={source.enabled}
                      disabled={!source.connected && !["obsidian", "markdown_folder"].includes(source.source)}
                      onChange={(e) =>
                        setSources(
                          sources.map((item) =>
                            item.source === source.source ? { ...item, enabled: e.target.checked } : item,
                          ),
                        )
                      }
                    />{" "}
                    代理AIが使う
                  </label>
                </div>
                <input
                  value={source.scope}
                  placeholder={source.source === "obsidian" || source.source === "markdown_folder" ? "Markdownフォルダの絶対パス" : "利用範囲"}
                  onChange={(e) =>
                    setSources(
                      sources.map((item) =>
                        item.source === source.source ? { ...item, scope: e.target.value } : item,
                      ),
                    )
                  }
                />
                <button onClick={() => saveSource(source)}>保存</button>
                {source.connected && source.enabled && ["obsidian", "markdown_folder"].includes(source.source) && (
                  <button onClick={() => void syncSource(source)}>今すぐ同期</button>
                )}
              </div>
            ))}
          </section>

          <section style={sectionStyle}>
            <h3 style={{ marginTop: 0 }}>公開可能な情報</h3>
            {disclosure && (
              <>
                <p>
                  <Status>上限: {disclosure.max_sensitivity}</Status>{" "}
                  <Status>予定: {disclosure.share_schedule ? "公開可" : "非公開"}</Status>{" "}
                  <Status>スキル: {disclosure.share_skills ? "公開可" : "非公開"}</Status>
                </p>
                <select
                  value={disclosure.max_sensitivity}
                  onChange={(e) => setDisclosure({ ...disclosure, max_sensitivity: e.target.value })}
                >
                  {sensitivities.map((sensitivity) => (
                    <option key={sensitivity}>{sensitivity}</option>
                  ))}
                </select>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))" }}>
                  {memoryTypes.map((type) => (
                    <label key={type}>
                      <input
                        type="checkbox"
                        checked={allowed.has(type)}
                        onChange={(e) => {
                          const next = new Set(allowed);
                          if (e.target.checked) next.add(type);
                          else next.delete(type);
                          setDisclosure({ ...disclosure, allowed_memory_types: Array.from(next) });
                        }}
                      />{" "}
                      {type}
                    </label>
                  ))}
                </div>
                <label>
                  <input
                    type="checkbox"
                    checked={disclosure.share_schedule}
                    onChange={(e) => setDisclosure({ ...disclosure, share_schedule: e.target.checked })}
                  />{" "}
                  空き時間を公開可
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={disclosure.share_skills}
                    onChange={(e) => setDisclosure({ ...disclosure, share_skills: e.target.checked })}
                  />{" "}
                  スキルを公開可
                </label>
                <p>
                  相手別の上書きは <button onClick={onOpenPeers}>接続相手</button> で確認します。
                </p>
                <button onClick={saveDisclosure}>保存</button>
              </>
            )}
          </section>

          <section style={sectionStyle}>
            <h3 style={{ marginTop: 0 }}>権限</h3>
            {Object.entries(delegationLabels).map(([key, label]) => (
              <label key={key} style={{ display: "block" }}>
                <input
                  type="checkbox"
                  checked={delegation?.rules[key] ?? false}
                  onChange={(e) => saveDelegation(patchRule(delegation, key, e.target.checked))}
                />{" "}
                {label} <Status>{delegation?.rules[key] ? "委任中" : "本人判断"}</Status>
              </label>
            ))}
          </section>

          <section style={sectionStyle}>
            <h3 style={{ marginTop: 0 }}>日程の好み</h3>
            <p>代理AIが候補を評価するときの希望時間帯と、避けたい時間帯です。</p>
            {meetingPreferences ? (
              <>
                <TimeRangeEditor
                  label="希望時間帯"
                  ranges={meetingPreferences.preferred_time_ranges}
                  onChange={(ranges) => setMeetingPreferences({ ...meetingPreferences, preferred_time_ranges: ranges })}
                />
                <TimeRangeEditor
                  label="避けたい時間帯"
                  ranges={meetingPreferences.avoid_time_ranges}
                  onChange={(ranges) => setMeetingPreferences({ ...meetingPreferences, avoid_time_ranges: ranges })}
                />
                <button onClick={() => void saveMeetingPreferences()}>日程の好みを保存</button>
              </>
            ) : <p>代理AIを有効化すると設定できます。</p>}
          </section>

          <section style={sectionStyle}>
            <h3 style={{ marginTop: 0 }}>承認ルール</h3>
            {Object.entries(approvalLabels).map(([key, label]) => (
              <label key={key} style={{ display: "block" }}>
                <input
                  type="checkbox"
                  checked={approvalRules?.rules[key] ?? true}
                  onChange={(e) => saveApprovalRules(patchRule(approvalRules, key, e.target.checked))}
                />{" "}
                {label} <Status>{approvalRules?.rules[key] ? "本人確認あり" : "自動許可"}</Status>
              </label>
            ))}
          </section>

          <section style={sectionStyle}>
            <h3 style={{ marginTop: 0 }}>接続AI</h3>
            {providers.map((provider) => (
              <p key={provider.provider}>
                <strong>{provider.provider}</strong>{" "}
                <Status>{provider.installed ? "検出済み" : "未検出"}</Status>{" "}
                <Status>{provider.authenticated ? "認証済み" : "未認証"}</Status>
              </p>
            ))}
            <button onClick={load}>再検出</button>
          </section>
        </div>
      )}
    </main>
  );
}
