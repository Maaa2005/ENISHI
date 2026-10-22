import { describe, expect, it, vi } from "vitest";
import { listenForDeepLinkInvites } from "./useDeepLinkInvite";

describe("listenForDeepLinkInvites", () => {
  it("ブラウザではdeep-linkを初期化せずエラーも出さない", () => {
    const getCurrent = vi.fn();
    const onOpenUrl = vi.fn();
    const onError = vi.fn();

    listenForDeepLinkInvites(vi.fn(), onError, { isTauri: () => false, getCurrent, onOpenUrl });

    expect(getCurrent).not.toHaveBeenCalled();
    expect(onOpenUrl).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
  });

  it("デスクトップでは起動時の招待リンクを渡す", async () => {
    const onInvite = vi.fn();
    const stop = vi.fn();

    const dispose = listenForDeepLinkInvites(onInvite, vi.fn(), {
      isTauri: () => true,
      getCurrent: async () => ["https://example.com", "enishi://add/payload"],
      onOpenUrl: async () => stop,
    });
    await vi.waitFor(() => expect(onInvite).toHaveBeenCalledWith("enishi://add/payload"));

    dispose();
    expect(stop).toHaveBeenCalledOnce();
  });

  it("デスクトップで初期化に失敗したら案内を出す", async () => {
    const onError = vi.fn();
    vi.spyOn(console, "error").mockImplementation(() => undefined);

    listenForDeepLinkInvites(vi.fn(), onError, {
      isTauri: () => true,
      getCurrent: async () => { throw new Error("unavailable"); },
      onOpenUrl: async () => () => undefined,
    });

    await vi.waitFor(() => expect(onError).toHaveBeenCalledWith(expect.stringContaining("招待リンクを開けませんでした")));
  });
});
