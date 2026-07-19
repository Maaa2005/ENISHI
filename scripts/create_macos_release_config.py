#!/usr/bin/env python3
"""配布ビルド用Tauri設定を公開鍵とHTTPS endpointから生成する。"""

import argparse
import json
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--endpoint",
        default="https://github.com/Maaa2005/ENISHI/releases/latest/download/latest.json",
    )
    args = parser.parse_args()

    public_key = os.environ.get("TAURI_UPDATER_PUBLIC_KEY", "").strip()
    if not public_key or "PLACEHOLDER" in public_key:
        raise SystemExit("TAURI_UPDATER_PUBLIC_KEY is required")
    if not args.endpoint.startswith("https://"):
        raise SystemExit("updater endpoint must use HTTPS")

    root = Path(__file__).resolve().parents[1]
    base = json.loads((root / "apps/desktop/src-tauri/tauri.bundle.conf.json").read_text())
    base.setdefault("bundle", {})["createUpdaterArtifacts"] = True
    base.setdefault("plugins", {})["updater"] = {
        "pubkey": public_key,
        "endpoints": [args.endpoint],
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n")
    output.chmod(0o600)
    print(output)


if __name__ == "__main__":
    main()
