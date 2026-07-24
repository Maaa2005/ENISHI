#!/usr/bin/env python3
"""公開AUN SchemaをLocal Core配布packageへ同期する。"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "packages/protocol/schemas/negotiation-message.schema.json"
TARGET = (
    ROOT
    / "services/local-core/enishi_core/protocol/negotiation-message.schema.json"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="生成コピーが正本と一致するかだけを検証する",
    )
    args = parser.parse_args()
    expected = SOURCE.read_bytes()
    if args.check:
        if not TARGET.exists() or TARGET.read_bytes() != expected:
            parser.error(
                "protocol schema copy is stale; run scripts/sync_protocol_schema.py"
            )
        return 0

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_bytes(expected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
