import { useEffect, useMemo, useState } from "react";
import type { ApiClient } from "../services/api";
import type { PeerDisclosurePolicyRead, PeerRead } from "../types";

const memoryTypes = [
  "identity",
  "preference",
  "skill",
  "project",
  "decision",
  "policy",
  "communication",
  "environment",
  "negative_preference",
  "episodic",
  "relationship",
  "schedule",
];

const sensitivities = ["public", "internal", "private", "restricted", "secret"];

const sectionStyle: React.CSSProperties = {
  border: "1px solid #ddd",
  borderRadius: 8,
  padding: "1rem",
};

function statusLabel(status: string): string {
  if (status === "pending") return "承認待ち";
  if (status === "trusted") return "信頼済み";
  if (status === "blocked") return "ブロック";
  return status;
}

function DisclosureEditor({
  policy,
  onChange,
  onSave,
}: {
  policy: PeerDisclosurePolicyRead | null;
  onChange: (policy: PeerDisclosurePolicyRead) => void;
  onSave: () => void;
}) {
  if (!policy) return <p>ピアを選択してください</p>;
  const allowed = new Set(policy.allowed_memory_types);
  const patch = (next: Partial<PeerDisclosurePolicyRead>) => onChange({ ...policy, ...next });

  return (
    <div style={{ display: "grid", gap: "0.75rem" }}>
      <label>
        機密度上限{" "}
        <select
          value={policy.max_sensitivity}
          onChange={(e) => patch({ max_sensitivity: e.target.value })}
        >
          {sensitivities.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </label>
      <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
        <label>
          <input
            type="checkbox"
            checked={policy.share_schedule}
            onChange={(e) => patch({ share_schedule: e.target.checked })}
          />{" "}
          schedule共有
        </label>
        <label>
          <input
            type="checkbox"
            checked={policy.share_skills}
            onChange={(e) => patch({ share_skills: e.target.checked })}
          />{" "}
          skill共有
        </label>
      </div>
      <fieldset style={{ border: "1px solid #ddd", borderRadius: 6 }}>
        <legend>allowed_memory_types</legend>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
          {memoryTypes.map((type) => (
            <label key={type}>
              <input
                type="checkbox"
                checked={allowed.has(type)}
                onChange={(e) => {
                  const next = new Set(allowed);
                  if (e.target.checked) next.add(type);
                  else next.delete(type);
                  patch({ allowed_memory_types: Array.from(next) });
                }}
              />{" "}
              {type}
            </label>
          ))}
        </div>
      </fieldset>
      <button onClick={onSave}>公開設定を保存</button>
    </div>
  );
}

export function PeersPage({ client }: { client: ApiClient | null }) {
  const [identity, setIdentity] = useState("");
  const [peers, setPeers] = useState<PeerRead[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [policy, setPolicy] = useState<PeerDisclosurePolicyRead | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [agentId, setAgentId] = useState("");
  const [publicKey, setPublicKey] = useState("");

  const selectedPeer = useMemo(
    () => peers.find((peer) => peer.agent_id === selected) ?? null,
    [peers, selected],
  );

  const load = async () => {
    if (!client) return;
    setError(null);
    try {
      const [node, peerRows] = await Promise.all([client.getNodeIdentity(), client.listPeers()]);
      setIdentity(`${node.agent_id} / ${node.fingerprint}`);
      setPeers(peerRows);
      if (!selected && peerRows[0]) setSelected(peerRows[0].agent_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => {
    void load();
  }, [client]);

  useEffect(() => {
    if (!client || !selected) {
      setPolicy(null);
      return;
    }
    void client
      .getPeerDisclosure(selected)
      .then(setPolicy)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  }, [client, selected]);

  const register = async () => {
    if (!client) return;
    await client.createPeer({ agent_id: agentId, display_name: displayName, public_key: publicKey });
    setAgentId("");
    setDisplayName("");
    setPublicKey("");
    await load();
  };

  const trust = async (peer: PeerRead) => {
    if (!client) return;
    await client.trustPeer(peer.agent_id);
    await load();
  };

  const block = async (peer: PeerRead) => {
    if (!client) return;
    await client.blockPeer(peer.agent_id);
    await load();
  };

  const savePolicy = async () => {
    if (!client || !selected || !policy) return;
    setPolicy(await client.putPeerDisclosure(selected, policy));
  };

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "2rem", maxWidth: 1100 }}>
      <h1>接続相手</h1>
      {error && <p style={{ color: "#c0392b" }}>{error}</p>}
      <p>自ノード: {identity || "確認中"}</p>

      <section style={{ ...sectionStyle, marginBottom: "1rem" }}>
        <h3 style={{ marginTop: 0 }}>ペアリング登録</h3>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <input placeholder="agent_id" value={agentId} onChange={(e) => setAgentId(e.target.value)} />
          <input
            placeholder="表示名"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
          <input
            placeholder="公開鍵"
            value={publicKey}
            onChange={(e) => setPublicKey(e.target.value)}
            style={{ minWidth: 280 }}
          />
          <button onClick={register} disabled={!client || !agentId || !displayName || !publicKey}>
            登録
          </button>
        </div>
      </section>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(320px, 1fr) 1fr", gap: "1rem" }}>
        <section style={sectionStyle}>
          <h3 style={{ marginTop: 0 }}>ピア一覧</h3>
          {peers.length === 0 && <p>登録済みピアがありません</p>}
          {peers.map((peer) => (
            <button
              key={peer.agent_id}
              onClick={() => setSelected(peer.agent_id)}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                marginBottom: "0.5rem",
                padding: "0.75rem",
                borderRadius: 6,
                border: "1px solid #ccc",
                background: peer.agent_id === selected ? "#eef" : "#fff",
              }}
            >
              <strong>{peer.display_name}</strong> {statusLabel(peer.status)}
              <br />
              <span style={{ color: "#555" }}>{peer.fingerprint}</span>
            </button>
          ))}
          {selectedPeer && (
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button onClick={() => trust(selectedPeer)} disabled={selectedPeer.status === "trusted"}>
                trust
              </button>
              <button onClick={() => block(selectedPeer)} disabled={selectedPeer.status === "blocked"}>
                block
              </button>
            </div>
          )}
        </section>
        <section style={sectionStyle}>
          <h3 style={{ marginTop: 0 }}>相手別公開設定</h3>
          <DisclosureEditor policy={policy} onChange={setPolicy} onSave={savePolicy} />
        </section>
      </div>
    </main>
  );
}
