"""Relay bearer tokenの生成・ハッシュ化CLI。"""

import argparse
import getpass
import hashlib
import secrets


def main() -> None:
    parser = argparse.ArgumentParser(description="Relay token SHA-256 helper")
    parser.add_argument(
        "--generate",
        action="store_true",
        help="新しいtokenを生成し、そのtokenとSHA-256を一度だけ表示する",
    )
    args = parser.parse_args()

    token = secrets.token_urlsafe(32) if args.generate else getpass.getpass("Relay token: ")
    if not token:
        raise SystemExit("token must not be empty")
    if args.generate:
        print(f"token={token}")
    print(f"sha256={hashlib.sha256(token.encode('utf-8')).hexdigest()}")


if __name__ == "__main__":
    main()
