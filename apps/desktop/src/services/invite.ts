import type { IdentityCardRead } from "../types";

const INVITE_PREFIX = "enishi://add/";

function encodeBase64Url(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function decodeBase64Url(value: string): string {
  if (!/^[A-Za-z0-9_-]+$/.test(value)) throw new Error("招待リンクの形式が正しくありません");
  const padded = value.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(value.length / 4) * 4, "=");
  const binary = atob(padded);
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
}

function isIdentityCard(value: unknown): value is IdentityCardRead {
  if (!value || typeof value !== "object") return false;
  const card = value as Record<string, unknown>;
  return (
    (card.version === "enishi-card/1" || card.version === "enishi-card/2") &&
    typeof card.agent_id === "string" &&
    typeof card.personal_agent_id === "string" &&
    typeof card.public_key === "string" &&
    typeof card.fingerprint === "string" &&
    typeof card.signature === "string"
  );
}

export function encodeAgentInvite(card: IdentityCardRead): string {
  return `${INVITE_PREFIX}${encodeBase64Url(JSON.stringify(card))}`;
}

export function decodeAgentInvite(value: string): IdentityCardRead {
  const normalized = value.trim();
  if (!normalized.startsWith(INVITE_PREFIX)) {
    throw new Error("enishi://add/ で始まる招待リンクを入力してください");
  }
  let decoded: unknown;
  try {
    decoded = JSON.parse(decodeBase64Url(normalized.slice(INVITE_PREFIX.length)));
  } catch (error) {
    if (error instanceof Error && error.message.includes("招待リンク")) throw error;
    throw new Error("招待リンクを読み取れませんでした");
  }
  if (!isIdentityCard(decoded)) throw new Error("招待リンクに有効なAgent Cardが含まれていません");
  return decoded;
}

export function isAgentInvite(value: string): boolean {
  return value.startsWith(INVITE_PREFIX);
}
