import { useEffect, useState } from "react";
import type { ApiClient } from "../services/api";
import type { MetricsExperimentRead, MetricsSummary } from "../types";

const defaultTemplate =
  "田中様\n\nお世話になっております。\n来週、AIエージェントの企画について30分ほどお話しする時間をいただきたいです。\n可能であれば午後を希望しております。\nご都合のよい時間をお知らせください。\n\nよろしくお願いいたします。";

export function MetricsPage({ client }: { client: ApiClient | null }) {
  const [summary, setSummary] = useState<MetricsSummary | null>(null);
  const [experiment, setExperiment] = useState<MetricsExperimentRead | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [template, setTemplate] = useState(defaultTemplate);
  const [roundTrips, setRoundTrips] = useState(2);
  const [usesDelta, setUsesDelta] = useState(true);

  useEffect(() => {
    if (!client) return;
    let cancelled = false;
    void client
      .getMetricsSummary()
      .then((data) => {
        if (!cancelled) setSummary(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [client]);

  const runExperiment = async () => {
    if (!client) return;
    setError(null);
    try {
      const result = await client.runMetricsExperiment({
        template,
        round_trips: roundTrips,
        uses_delta: usesDelta,
      });
      setExperiment(result);
      setSummary(await client.getMetricsSummary());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const rows = experiment?.methods ?? summary?.methods ?? [];
  const reductionRate = experiment?.reduction_rate ?? summary?.reduction_rate ?? null;

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "2rem", maxWidth: 720 }}>
      <h1>メトリクス</h1>
      {error && (
        <p role="alert" style={{ color: "#c0392b" }}>
          {error}
        </p>
      )}
      <section style={{ border: "1px solid #ddd", borderRadius: 8, padding: "1rem", marginBottom: "1rem" }}>
        <h3 style={{ marginTop: 0 }}>メール方式との比較実験</h3>
        <label>
          往復数{" "}
          <input
            type="number"
            min={1}
            max={10}
            value={roundTrips}
            onChange={(e) => setRoundTrips(Number(e.target.value))}
            style={{ width: 72 }}
          />
        </label>{" "}
        <label>
          <input
            type="checkbox"
            checked={usesDelta}
            onChange={(e) => setUsesDelta(e.target.checked)}
          />{" "}
          deltaあり
        </label>
        <textarea
          value={template}
          onChange={(e) => setTemplate(e.target.value)}
          rows={7}
          style={{ display: "block", width: "100%", margin: "0.75rem 0" }}
        />
        <button onClick={runExperiment} disabled={!client}>
          実行
        </button>
      </section>

      {summary === null && !error && <p>読み込み中…</p>}
      {rows.length === 0 && summary !== null && <p>まだ計測データがありません</p>}
      {rows.length > 0 && (
        <>
          {experiment && (
            <section style={{ marginBottom: "1rem" }}>
              <h3>測定条件</h3>
              <p>
                template: {experiment.template.length} chars / 往復数: {experiment.round_trips} / delta:{" "}
                {experiment.uses_delta ? "あり" : "なし"}
              </p>
              <pre style={{ background: "#f6f6f6", padding: "0.75rem", overflowX: "auto" }}>
                {JSON.stringify(experiment.structured_json, null, 2)}
              </pre>
            </section>
          )}
          <table style={{ borderCollapse: "collapse", width: "100%" }}>
            <thead>
              <tr>
                {[
                  "方式",
                  "入力トークン",
                  "出力トークン",
                  "合計",
                  "LLM呼び出し",
                  "メッセージ数",
                ].map((h) => (
                  <th
                    key={h}
                    style={{
                      textAlign: "left",
                      padding: "0.25rem 0.5rem",
                      borderBottom: "1px solid #ccc",
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((m) => (
                <tr key={m.method}>
                  <td style={{ padding: "0.25rem 0.5rem" }}>{m.method}</td>
                  <td style={{ padding: "0.25rem 0.5rem" }}>{m.input_tokens}</td>
                  <td style={{ padding: "0.25rem 0.5rem" }}>{m.output_tokens}</td>
                  <td style={{ padding: "0.25rem 0.5rem" }}>{m.total_tokens}</td>
                  <td style={{ padding: "0.25rem 0.5rem" }}>{m.llm_calls}</td>
                  <td style={{ padding: "0.25rem 0.5rem" }}>{m.message_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p>
            削減率:{" "}
            {reductionRate === null
              ? "計測データ不足"
              : `${reductionRate.toFixed(1)}%`}
          </p>
        </>
      )}
    </main>
  );
}
