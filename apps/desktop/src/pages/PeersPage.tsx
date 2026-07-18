import { useEffect, useMemo, useState } from "react";
import QRCode from "qrcode";
import type { ApiClient } from "../services/api";
import type { PeerDisclosurePolicyRead, PeerRead } from "../types";
import { decodeAgentInvite, encodeAgentInvite } from "../services/invite";
import { useAppStore } from "../stores/appStore";

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

const sensitivities = ["public", "internal", "private"];

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

export function PeersPage({
  client,
  incomingInvite,
  onInviteConsumed,
}: {
  client: ApiClient | null;
  incomingInvite?: string | null;
  onInviteConsumed?: () => void;
}) {
  const users = useAppStore((state) => state.users);
  const [identity, setIdentity] = useState("");
  const [personalIdentity, setPersonalIdentity] = useState("");
  const [peers, setPeers] = useState<PeerRead[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [policy, setPolicy] = useState<PeerDisclosurePolicyRead | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [agentId, setAgentId] = useState("");
  const [personalAgentId, setPersonalAgentId] = useState("");
  const [aliases, setAliases] = useState("");
  const [publicKey, setPublicKey] = useState("");
  const [ownInvite, setOwnInvite] = useState("");
  const [qrDataUrl, setQrDataUrl] = useState("");
  const [inviteInput, setInviteInput] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  const selectedPeer = useMemo(
    () => peers.find((peer) => peer.agent_id === selected) ?? null,
    [peers, selected],
  );

  const runAction = async (action: () => Promise<void>) => {
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const load = async () => {
    if (!client) return;
    setError(null);
    try {
      const [node, peerRows, personal, card] = await Promise.all([
        client.getNodeIdentity(),
        client.listPeers(),
        users[0] ? client.getAgentIdentity(users[0].id) : Promise.resolve(null),
        users[0] ? client.getIdentityCard(users[0].id) : Promise.resolve(null),
      ]);
      setIdentity(`${node.agent_id} / ${node.fingerprint}`);
      setPersonalIdentity(personal?.personal_agent_id ?? "");
      setOwnInvite(card ? encodeAgentInvite(card) : "");
      setPeers(peerRows);
      if (!selected && peerRows[0]) setSelected(peerRows[0].agent_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => {
    void load();
  }, [client, users]);

  useEffect(() => {
    let cancelled = false;
    if (!ownInvite) {
      setQrDataUrl("");
      return;
    }
    void QRCode.toDataURL(ownInvite, { width: 220, margin: 1, errorCorrectionLevel: "L" })
      .then((url) => { if (!cancelled) setQrDataUrl(url); })
      .catch((err: unknown) => { if (!cancelled) setError(err instanceof Error ? err.message : String(err)); });
    return () => { cancelled = true; };
  }, [ownInvite]);

  useEffect(() => {
    if (!incomingInvite) return;
    setInviteInput(incomingInvite);
    setNotice("招待リンクを受け取りました。内容を検証してから承認待ちに追加してください。");
  }, [incomingInvite]);

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
    await runAction(async () => {
      await client.createPeer({
        agent_id: agentId,
        personal_agent_id: personalAgentId || undefined,
        aliases: aliases.split(",").map((value) => value.trim()).filter(Boolean),
        display_name: displayName,
        public_key: publicKey,
      });
      setAgentId("");
      setPersonalAgentId("");
      setAliases("");
      setDisplayName("");
      setPublicKey("");
      await load();
    });
  };

  const registerInvite = async () => {
    if (!client) return;
    await runAction(async () => {
      const card = decodeAgentInvite(inviteInput);
      const peer = await client.createPeerFromCard(card);
      setSelected(peer.agent_id);
      setInviteInput("");
      setNotice(`${peer.display_name}を承認待ちに追加しました。fingerprintを相手と照合してから信頼してください。`);
      onInviteConsumed?.();
      await load();
    });
  };

  const copyInvite = async () => {
    await runAction(async () => {
      await navigator.clipboard.writeText(ownInvite);
      setNotice("招待リンクをコピーしました。");
    });
  };

  const trust = async (peer: PeerRead) => {
    if (!client) return;
    await runAction(async () => {
      await client.trustPeer(peer.agent_id);
      await load();
    });
  };

  const block = async (peer: PeerRead) => {
    if (!client) return;
    await runAction(async () => {
      await client.blockPeer(peer.agent_id);
      await load();
    });
  };

  const savePolicy = async () => {
    if (!client || !selected || !policy) return;
    await runAction(async () => {
      setPolicy(await client.putPeerDisclosure(selected, policy));
    });
  };

  return (
    <main className="page peers-page">
      <header className="page-header">
        <div><p className="eyebrow">TRUSTED CONNECTIONS</p><h1>接続相手</h1><p className="subtitle">署名付きAgent Cardを交換し、fingerprintを確認して信頼を確定します。</p></div>
      </header>
      {error && <p className="alert error">{error}</p>}
      {notice && <p className="peer-notice">{notice}</p>}

      <div className="peer-invite-grid">
        <section className="panel peer-share-card">
          <div><p className="eyebrow">MY AGENT CARD</p><h2>自分の名刺を共有</h2><p>QRを相手の端末で読み取るか、招待リンクを安全な既存チャネルで送ります。</p></div>
          <div className="peer-share-body">
            {qrDataUrl ? <img src={qrDataUrl} alt="自分のENISHI Agent Card QRコード" /> : <div className="peer-qr-placeholder">QR生成中</div>}
            <dl className="peer-identity-facts">
              <div><dt>代理AI</dt><dd>{personalIdentity || "確認中"}</dd></div>
              <div><dt>端末 / fingerprint</dt><dd>{identity || "確認中"}</dd></div>
            </dl>
          </div>
          <div className="peer-invite-link"><input readOnly value={ownInvite} aria-label="自分の招待リンク" /><button onClick={copyInvite} disabled={!ownInvite}>コピー</button></div>
        </section>

        <section className="panel peer-add-card">
          <div><p className="eyebrow">ADD CONNECTION</p><h2>相手の名刺を受け取る</h2><p>リンク内の署名・Agent ID・公開鍵fingerprintをLocal Coreが検証します。追加後も信頼は未確定です。</p></div>
          <textarea
            rows={6}
            placeholder="enishi://add/…"
            value={inviteInput}
            onChange={(event) => setInviteInput(event.target.value)}
            aria-label="相手の招待リンク"
          />
          <button className="primary-button" onClick={registerInvite} disabled={!client || !inviteInput.trim()}>
            署名を検証して承認待ちに追加
          </button>
          <small>リンクを開いて起動した場合も、自動で信頼せずこの確認画面で止まります。</small>
        </section>
      </div>

      <details className="peer-manual-entry">
        <summary>上級者向け: 公開鍵を手入力する</summary>
        <section style={{ ...sectionStyle, marginTop: "0.75rem" }}>
        <h3 style={{ marginTop: 0 }}>手動ペアリング登録</h3>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <input placeholder="端末Node ID" value={agentId} onChange={(e) => setAgentId(e.target.value)} />
          <input
            placeholder="Personal Agent ID"
            value={personalAgentId}
            onChange={(e) => setPersonalAgentId(e.target.value)}
          />
          <input
            placeholder="表示名"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
          <input
            placeholder="別名（カンマ区切り）"
            value={aliases}
            onChange={(e) => setAliases(e.target.value)}
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
      </details>

      <div className="peer-management-grid">
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
              {peer.personal_agent_id && (
                <><br /><span style={{ color: "#777" }}>{peer.personal_agent_id}</span></>
              )}
              {peer.aliases.length > 0 && (
                <><br /><span style={{ color: "#777" }}>別名: {peer.aliases.join("、")}</span></>
              )}
            </button>
          ))}
          {selectedPeer && (
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button onClick={() => trust(selectedPeer)} disabled={selectedPeer.status === "trusted"}>
                信頼する
              </button>
              <button onClick={() => block(selectedPeer)} disabled={selectedPeer.status === "blocked"}>
                ブロック
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
