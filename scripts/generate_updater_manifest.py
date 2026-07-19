#!/usr/bin/env python3
"""Tauri静的updater用latest.jsonを署名成果物から生成する。"""

import argparse
import json
import platform
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote


def target_name() -> str:
    machine = platform.machine()
    architecture = {"arm64": "aarch64", "aarch64": "aarch64", "x86_64": "x86_64"}.get(machine)
    if architecture is None:
        raise SystemExit(f"unsupported updater architecture: {machine}")
    return f"darwin-{architecture}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--repository", default="Maaa2005/ENISHI")
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--signature", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--notes", default="ENISHI release")
    args = parser.parse_args()

    normalized_tag = args.tag.removeprefix("v")
    if normalized_tag != args.version:
        raise SystemExit(f"tag/version mismatch: tag={args.tag} app_version={args.version}")
    artifact = Path(args.artifact)
    signature = Path(args.signature)
    if not artifact.is_file() or not signature.is_file():
        raise SystemExit("updater artifact and signature are required")
    signature_text = signature.read_text().strip()
    if not signature_text:
        raise SystemExit("updater signature is empty")

    url = (
        f"https://github.com/{args.repository}/releases/download/"
        f"{quote(args.tag, safe='')}/{quote(artifact.name, safe='')}"
    )
    manifest = {
        "version": args.version,
        "notes": args.notes,
        "pub_date": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "platforms": {
            target_name(): {
                "signature": signature_text,
                "url": url,
            }
        },
    }
    Path(args.output).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
