import { invoke } from "@tauri-apps/api/core";
import type { CoreConnection } from "../types";
import type { ApiClient } from "./api";

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/**
 * Local Coreへの接続情報を解決する。
 * Tauri内ではRustが生成したランダムポート・トークンを取得し、
 * ブラウザ開発時はVITE_CORE_PORT / VITE_CORE_TOKEN を使う。
 */
export async function resolveCoreConnection(): Promise<CoreConnection> {
  if (isTauri()) {
    return await invoke<CoreConnection>("get_core_connection");
  }
  return {
    port: Number(import.meta.env.VITE_CORE_PORT ?? 8765),
    token: String(import.meta.env.VITE_CORE_TOKEN ?? "dev-local-token"),
  };
}

interface WaitForCoreOptions {
  attempts?: number;
  intervalMs?: number;
  sleep?: (milliseconds: number) => Promise<void>;
}

/** Local Coreの起動とDBマイグレーションが完了するまで待つ。 */
export async function waitForCore(
  client: Pick<ApiClient, "health">,
  options: WaitForCoreOptions = {},
): Promise<void> {
  const attempts = options.attempts ?? 120;
  const intervalMs = options.intervalMs ?? 250;
  const sleep = options.sleep ?? ((milliseconds: number) => new Promise((resolve) => {
    window.setTimeout(resolve, milliseconds);
  }));
  let lastError: unknown = new Error("Local Coreが応答しません。");

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      const health = await client.health();
      if (health.status === "ok" && health.database_connected) return;
      lastError = new Error("Local Coreのデータベースを準備しています。");
    } catch (error) {
      lastError = error;
    }
    if (attempt < attempts - 1) await sleep(intervalMs);
  }

  const detail = lastError instanceof Error ? lastError.message : String(lastError);
  throw new Error(`Local Coreの起動を確認できませんでした: ${detail}`);
}
