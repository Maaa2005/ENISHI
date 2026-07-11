import { invoke } from "@tauri-apps/api/core";
import type { CoreConnection } from "../types";

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
