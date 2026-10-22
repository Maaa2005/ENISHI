import { useEffect, useState } from "react";
import { getCurrent, onOpenUrl } from "@tauri-apps/plugin-deep-link";
import { isTauri } from "../services/backend";
import { isAgentInvite } from "../services/invite";

const FAILURE_MESSAGE = "招待リンクを開けませんでした。リンクをコピーして接続相手画面から追加してください。";

export interface DeepLinkDeps {
  isTauri: () => boolean;
  getCurrent: () => Promise<string[] | null>;
  onOpenUrl: (handler: (urls: string[]) => void) => Promise<() => void>;
}

const defaultDeps: DeepLinkDeps = { isTauri, getCurrent, onOpenUrl };

export function listenForDeepLinkInvites(
  onInvite: (invite: string) => void,
  onError: (message: string | null) => void,
  deps: DeepLinkDeps = defaultDeps,
): () => void {
  // ブラウザで画面だけ動かすデモにはdeep-linkプラグインがないため初期化しない。
  if (!deps.isTauri()) return () => undefined;

  let unlisten: (() => void) | undefined;
  let disposed = false;
  const acceptUrls = (urls: string[] | null) => {
    const invite = urls?.find(isAgentInvite);
    if (!invite || disposed) return;
    onError(null);
    onInvite(invite);
  };
  const reportFailure = () => {
    if (disposed) return;
    // URLや例外本文にはAgent Cardが含まれ得るため出力しない。
    console.error("ENISHI deep-link initialization failed");
    onError(FAILURE_MESSAGE);
  };

  void deps.getCurrent().then(acceptUrls).catch(reportFailure);
  void deps.onOpenUrl(acceptUrls)
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
}

export function useDeepLinkInvite(
  onInvite: (invite: string) => void,
): string | null {
  const [error, setError] = useState<string | null>(null);

  useEffect(() => listenForDeepLinkInvites(onInvite, setError), [onInvite]);

  return error;
}
