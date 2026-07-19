import { relaunch } from "@tauri-apps/plugin-process";
import { check, type Update } from "@tauri-apps/plugin-updater";
import { useRef, useState } from "react";

type UpdateState = "idle" | "checking" | "available" | "current" | "installing" | "error";

export function UpdateControl() {
  const pending = useRef<Update | null>(null);
  const [state, setState] = useState<UpdateState>("idle");
  const [version, setVersion] = useState<string | null>(null);
  const [message, setMessage] = useState("配布版の署名済み更新を確認します。");

  async function checkForUpdate() {
    setState("checking");
    setMessage("更新を確認しています…");
    try {
      const update = await check();
      pending.current = update;
      if (!update) {
        setState("current");
        setMessage("最新バージョンです。");
        return;
      }
      setVersion(update.version);
      setState("available");
      setMessage(`バージョン ${update.version} を利用できます。`);
    } catch {
      setState("error");
      setMessage("更新情報を取得できません。開発版では利用できない場合があります。");
    }
  }

  async function installUpdate() {
    if (!pending.current) return;
    setState("installing");
    setMessage(`バージョン ${version ?? "新しい版"} を検証・インストールしています…`);
    try {
      await pending.current.downloadAndInstall();
      await relaunch();
    } catch {
      setState("error");
      setMessage("更新を適用できませんでした。現在のバージョンは維持されています。");
    }
  }

  return (
    <section className="panel update-panel">
      <div>
        <p className="eyebrow">SOFTWARE UPDATE</p>
        <h2>ENISHIを更新</h2>
        <p role={state === "error" ? "alert" : undefined}>{message}</p>
      </div>
      {state === "available" ? (
        <button className="primary-button" onClick={() => void installUpdate()}>
          更新して再起動
        </button>
      ) : (
        <button
          className="secondary-button"
          onClick={() => void checkForUpdate()}
          disabled={state === "checking" || state === "installing"}
        >
          {state === "checking" ? "確認中…" : "更新を確認"}
        </button>
      )}
    </section>
  );
}
