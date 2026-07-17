"""配布版デスクトップに同梱するLocal Coreのエントリポイント。"""

import argparse

import uvicorn

from enishi_core.main import app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ENISHI Local Core sidecar")
    parser.add_argument("--port", required=True, type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 1 <= args.port <= 65535:
        raise SystemExit("port must be between 1 and 65535")
    # 配布版でも外部インターフェースへ公開しない。hostは引数化しない。
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
