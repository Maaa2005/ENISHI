import { useEffect, useState } from "react";
import { getCurrent, onOpenUrl } from "@tauri-apps/plugin-deep-link";
import { isAgentInvite } from "../services/invite";

export function useDeepLinkInvite(
  onInvite: (invite: string) => void,
): string | null {
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let unlisten: (() => void) | undefined;
    let disposed = false;
    const acceptUrls = (urls: string[] | null) => {
      const invite = urls?.find(isAgentInvite);
      if (!invite || disposed) return;
      setError(null);
      onInvite(invite);
    };
    const reportFailure = () => {
      if (disposed) return;
      // URLや例外本文にはAgent Cardが含まれ得るため出力しない。
      console.error("ENISHI deep-link initialization failed");
      setError("招待リンクを開けませんでした。リンクをコピーして接続相手画面から追加してください。");
    };

    void getCurrent().then(acceptUrls).catch(reportFailure);
    void onOpenUrl(acceptUrls)
      .then((stop) => {
        if (disposed) {
          stop();
        } else {
          unlisten = stop;
        }
      })
      .catch(reportFailure);

    return () => {
      disposed = true;
      unlisten?.();
    };
  }, [onInvite]);

  return error;
}
