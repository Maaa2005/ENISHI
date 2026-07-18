import { describe, expect, it } from "vitest";
import type { IdentityCardRead } from "../types";
import { decodeAgentInvite, encodeAgentInvite, isAgentInvite } from "./invite";

const card: IdentityCardRead = {
  version: "enishi-card/2",
  agent_id: "node_1",
  personal_agent_id: "agent_1",
  public_key: "public-key",
  fingerprint: "aa:bb:cc",
  profile: { display_name: "水野先生" },
  capabilities: { timezone: "Asia/Tokyo" },
  relay_endpoint: "http://relay.invalid",
  issued_at: "2026-07-19T00:00:00Z",
  signature: "signature",
};

describe("Agent Card invite", () => {
  it("日本語を含むカードをenishi://addリンクへ往復変換する", () => {
    const invite = encodeAgentInvite(card);
    expect(isAgentInvite(invite)).toBe(true);
    expect(decodeAgentInvite(invite)).toEqual(card);
  });

  it("別schemeや壊れたpayloadを拒否する", () => {
    expect(() => decodeAgentInvite("https://example.com/invite")).toThrow("enishi://add/");
    expect(() => decodeAgentInvite("enishi://add/not-json")).toThrow();
  });
});
