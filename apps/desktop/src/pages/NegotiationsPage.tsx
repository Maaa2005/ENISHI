import { useEffect, useState } from "react";
import type { ApiClient } from "../services/api";
import { useNegotiationStore } from "../stores/negotiationStore";
import type { NegotiationMessageRead, NegotiationMetrics } from "../types";

const sectionStyle: React.CSSProperties = {
  border: "1px solid #ddd",
  borderRadius: 8,
  padding: "1rem",
};

function statusLabel(status: string): string {
  if (status === "agreed") return "合意";
  if (status === "failed") return "不成立";
  if (status === "waiting_approval") return "承認待ち";
  return "進行中";
}

function MessageCard({ message }: { message: NegotiationMessageRead }) {
  const body = Object.keys(message.delta).length > 0 ? message.delta : message.payload;
  return (
    <li style={{ marginBottom: "0.75rem", listStyle: "none" }}>
      <div style={{ fontWeight: 600 }}>
        {message.message_type}{" "}
        <span style={{ fontWeight: 400, color: "#555" }}>
          {message.sender_agent_id} → {message.receiver_agent_id}
          {message.requires_human_approval ? "（要承認）" : "（承認不要）"}
        </span>
      </div>
      <pre
        style={{
          background: "#f6f6f6",
          padding: "0.5rem",
          borderRadius: 4,
          overflowX: "auto",
          margin: "0.25rem 0 0",
        }}
      >
        {JSON.stringify(body, null, 2)}
      </pre>
    </li>
  );
}

function MetricsPanel({ metrics }: { metrics: NegotiationMetrics }) {
  const rows = [metrics.structured, metrics.email];
  return (
    <div style={sectionStyle}>
      <h3 style={{ marginTop: 0 }}>トークン比較（実測値）</h3>
      <table style={{ borderCollapse: "collapse", width: "100%" }}>
        <thead>
          <tr>
            {["方式", "合計トークン", "LLM呼び出し", "メッセージ数"].map((h) => (
              <th key={h} style={{ textAlign: "left", padding: "0.25rem 0.5rem" }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.method}>
              <td style={{ padding: "0.25rem 0.5rem" }}>{row.method}</td>
              <td style={{ padding: "0.25rem 0.5rem" }}>{row.total_tokens}</td>
              <td style={{ padding: "0.25rem 0.5rem" }}>{row.llm_calls}</td>
              <td style={{ padding: "0.25rem 0.5rem" }}>{row.message_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p style={{ marginBottom: 0 }}>
        削減率:{" "}
        {metrics.reduction_rate === null ? "計測不能" : `${metrics.reduction_rate.toFixed(1)}%`}
      </p>
    </div>
  );
}

export function NegotiationsPage({ client }: { client: ApiClient | null }) {
  const { sessions, selectedSessionId, messages, metrics, loading, error, loadSessions, select, run } =
    useNegotiationStore();

  useEffect(() => {
    if (client) void loadSessions(client);
  }, [client, loadSessions]);

  const [initiatorUserId, setInitiatorUserId] = useState("");
  const [responderUserId, setResponderUserId] = useState("");
  const [topic, setTopic] = useState("打ち合わせ");
  const [duration, setDuration] = useState(30);
  const [dateStart, setDateStart] = useState("");
  const [dateEnd, setDateEnd] = useState("");
  const [timeStart, setTimeStart] = useState("13:00");
  const [timeEnd, setTimeEnd] = useState("18:00");
  const [intent, setIntent] = useState<"meeting.schedule" | "task.request">("meeting.schedule");
  const [taskTitle, setTaskTitle] = useState("資料作成");
  const [taskDescription, setTaskDescription] = useState("提案資料を作る");
  const [taskDeadline, setTaskDeadline] = useState("");
  const [taskHours, setTaskHours] = useState(1.5);

  const canRun =
    client !== null &&
    initiatorUserId !== "" &&
    responderUserId !== "" &&
    (intent === "task.request" ? taskTitle !== "" : topic !== "" && dateStart !== "" && dateEnd !== "");

  const handleRun = () => {
    if (!client || !canRun) return;
    if (intent === "task.request") {
      void run(client, {
        intent,
        initiator_user_id: initiatorUserId,
        responder_user_id: responderUserId,
        title: taskTitle,
        description: taskDescription,
        deadline: taskDeadline || null,
        estimated_hours: taskHours,
        conditions: {},
      });
    } else {
      void run(client, {
        intent,
        initiator_user_id: initiatorUserId,
        responder_user_id: responderUserId,
        topic,
        duration_minutes: duration,
        date_range: { start: dateStart, end: dateEnd },
        preferred_time_ranges: [{ start: timeStart, end: timeEnd }],
      });
    }
  };

  const filteredSessions = sessions.filter((session) => session.intent === intent);

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "2rem", maxWidth: 960 }}>
      <h1>交渉</h1>
      {error && (
        <p role="alert" style={{ color: "#c0392b" }}>
          {error}
        </p>
      )}

      <section style={{ ...sectionStyle, marginBottom: "1rem" }}>
        <h3 style={{ marginTop: 0 }}>新規交渉</h3>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
          <select value={intent} onChange={(e) => setIntent(e.target.value as typeof intent)}>
            <option value="meeting.schedule">meeting.schedule</option>
            <option value="task.request">task.request</option>
          </select>
          <input
            placeholder="依頼側ユーザーID"
            value={initiatorUserId}
            onChange={(e) => setInitiatorUserId(e.target.value)}
          />
          <input
            placeholder="相手側ユーザーID"
            value={responderUserId}
            onChange={(e) => setResponderUserId(e.target.value)}
          />
          {intent === "meeting.schedule" ? (
            <>
              <input placeholder="トピック" value={topic} onChange={(e) => setTopic(e.target.value)} />
              <input
                type="number"
                min={1}
                max={480}
                value={duration}
                onChange={(e) => setDuration(Number(e.target.value))}
                style={{ width: 80 }}
              />
              <input type="date" value={dateStart} onChange={(e) => setDateStart(e.target.value)} />
              <input type="date" value={dateEnd} onChange={(e) => setDateEnd(e.target.value)} />
              <input type="time" value={timeStart} onChange={(e) => setTimeStart(e.target.value)} />
              <input type="time" value={timeEnd} onChange={(e) => setTimeEnd(e.target.value)} />
            </>
          ) : (
            <>
              <input
                placeholder="タイトル"
                value={taskTitle}
                onChange={(e) => setTaskTitle(e.target.value)}
              />
              <input
                placeholder="説明"
                value={taskDescription}
                onChange={(e) => setTaskDescription(e.target.value)}
              />
              <input type="date" value={taskDeadline} onChange={(e) => setTaskDeadline(e.target.value)} />
              <input
                type="number"
                min={0}
                step={0.5}
                value={taskHours}
                onChange={(e) => setTaskHours(Number(e.target.value))}
                style={{ width: 90 }}
              />
            </>
          )}
          <button onClick={handleRun} disabled={!canRun || loading}>
            {loading ? "実行中…" : "実行"}
          </button>
        </div>
      </section>

      <div style={{ display: "flex", gap: "1rem", alignItems: "flex-start" }}>
        <section style={{ ...sectionStyle, width: 280, flexShrink: 0 }}>
          <h3 style={{ marginTop: 0 }}>セッション一覧</h3>
          {filteredSessions.length === 0 && <p>交渉履歴がありません</p>}
          <ul style={{ margin: 0, padding: 0 }}>
            {filteredSessions.map((session) => (
              <li key={session.id} style={{ listStyle: "none", marginBottom: "0.5rem" }}>
                <button
                  onClick={() => client && void select(client, session.id)}
                  style={{
                    width: "100%",
                    textAlign: "left",
                    padding: "0.5rem",
                    background: session.id === selectedSessionId ? "#eef" : "#fff",
                    border: "1px solid #ccc",
                    borderRadius: 4,
                    cursor: "pointer",
                  }}
                >
                  <div style={{ fontWeight: 600 }}>{session.topic}</div>
                  <div style={{ fontSize: "0.85rem", color: "#555" }}>
                    {session.intent} / {statusLabel(session.status)} / {session.created_at}
                    {session.pending_approval_id ? ` / approval ${session.pending_approval_id}` : ""}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </section>

        <div style={{ flexGrow: 1, display: "flex", flexDirection: "column", gap: "1rem" }}>
          <section style={sectionStyle}>
            <h3 style={{ marginTop: 0 }}>タイムライン</h3>
            {messages.length === 0 && <p>セッションを選択してください</p>}
            <ol style={{ margin: 0, padding: 0 }}>
              {messages.map((message) => (
                <MessageCard key={message.message_id} message={message} />
              ))}
            </ol>
          </section>
          {metrics && <MetricsPanel metrics={metrics} />}
        </div>
      </div>
    </main>
  );
}
