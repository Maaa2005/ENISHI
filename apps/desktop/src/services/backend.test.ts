import { describe, expect, it, vi } from "vitest";
import { waitForCore } from "./backend";

describe("waitForCore", () => {
  it("Local Coreが起動するまで再試行する", async () => {
    const health = vi.fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce({ status: "ok", version: "0.1.0", database_connected: true });
    const sleep = vi.fn().mockResolvedValue(undefined);

    await waitForCore({ health }, { attempts: 3, intervalMs: 1, sleep });

    expect(health).toHaveBeenCalledTimes(2);
    expect(sleep).toHaveBeenCalledOnce();
  });

  it("上限まで応答がなければ分かりやすいエラーにする", async () => {
    const health = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(waitForCore(
      { health },
      { attempts: 2, intervalMs: 1, sleep: async () => undefined },
    )).rejects.toThrow("Local Coreの起動を確認できませんでした");
  });
});
