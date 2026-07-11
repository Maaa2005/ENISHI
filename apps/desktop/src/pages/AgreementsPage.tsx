import { useEffect, useMemo, useState } from "react";
import type { ApiClient } from "../services/api";
import type { AgreementRead } from "../types";

const sectionStyle: React.CSSProperties = {
  border: "1px solid #ddd",
  borderRadius: 8,
  padding: "1rem",
};

export function AgreementsPage({ client }: { client: ApiClient | null }) {
  const [agreements, setAgreements] = useState<AgreementRead[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [intent, setIntent] = useState("");
  const [error, setError] = useState<string | null>(null);

  const selected = useMemo(
    () => agreements.find((agreement) => agreement.id === selectedId) ?? agreements[0] ?? null,
    [agreements, selectedId],
  );

  const load = async () => {
    if (!client) return;
    setError(null);
    try {
      const rows = await client.listAgreements({
        status: status || undefined,
        intent: intent || undefined,
      });
      setAgreements(rows);
      if (!selectedId && rows[0]) setSelectedId(rows[0].id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => {
    void load();
  }, [client, status, intent]);

  const changeStatus = async (next: "fulfilled" | "cancelled") => {
    if (!client || !selected) return;
    await client.patchAgreementStatus(selected.id, next);
    await load();
  };

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "2rem", maxWidth: 1100 }}>
      <h1>合意</h1>
      {error && <p style={{ color: "#c0392b" }}>{error}</p>}
      <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem" }}>
        <select value={intent} onChange={(e) => setIntent(e.target.value)}>
          <option value="">intentすべて</option>
          <option value="meeting.schedule">meeting.schedule</option>
          <option value="task.request">task.request</option>
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">statusすべて</option>
          <option value="active">active</option>
          <option value="fulfilled">fulfilled</option>
          <option value="cancelled">cancelled</option>
        </select>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "340px 1fr", gap: "1rem" }}>
        <section style={sectionStyle}>
          <h3 style={{ marginTop: 0 }}>Agreement一覧</h3>
          {agreements.length === 0 && <p>合意はありません</p>}
          {agreements.map((agreement) => (
            <button
              key={agreement.id}
              onClick={() => setSelectedId(agreement.id)}
              style={{
                width: "100%",
                textAlign: "left",
                padding: "0.75rem",
                marginBottom: "0.5rem",
                border: "1px solid #ccc",
                borderRadius: 6,
                background: agreement.id === selected?.id ? "#eef" : "#fff",
              }}
            >
              <strong>{agreement.intent}</strong> / {agreement.status}
              <br />
              <span style={{ color: "#555" }}>{agreement.agreed_at}</span>
            </button>
          ))}
        </section>

        <section style={sectionStyle}>
          <h3 style={{ marginTop: 0 }}>詳細</h3>
          {!selected && <p>合意を選択してください</p>}
          {selected && (
            <>
              <dl>
                <dt>session</dt>
                <dd>{selected.session_id}</dd>
                <dt>agents</dt>
                <dd>
                  {selected.initiator_agent_id} → {selected.responder_agent_id}
                </dd>
                <dt>status</dt>
                <dd>{selected.status}</dd>
              </dl>
              <pre style={{ background: "#f6f6f6", padding: "0.75rem", overflowX: "auto" }}>
                {JSON.stringify(selected.agreed_payload, null, 2)}
              </pre>
              <div style={{ display: "flex", gap: "0.5rem" }}>
                <button onClick={() => changeStatus("fulfilled")} disabled={selected.status !== "active"}>
                  fulfilled
                </button>
                <button onClick={() => changeStatus("cancelled")} disabled={selected.status !== "active"}>
                  cancelled
                </button>
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
