#!/bin/bash
# GitHub Actionsの一時KeychainへDeveloper ID証明書を安全にimportする。
set -eu

: "${APPLE_CERTIFICATE:?APPLE_CERTIFICATE is required}"
: "${APPLE_CERTIFICATE_PASSWORD:?APPLE_CERTIFICATE_PASSWORD is required}"
: "${KEYCHAIN_PASSWORD:?KEYCHAIN_PASSWORD is required}"
: "${RUNNER_TEMP:?RUNNER_TEMP is required}"

CERTIFICATE_PATH="$RUNNER_TEMP/enishi-certificate.p12"
KEYCHAIN_PATH="$RUNNER_TEMP/enishi-signing.keychain-db"

cleanup_certificate() {
  rm -f "$CERTIFICATE_PATH"
}
trap cleanup_certificate EXIT

CERTIFICATE_PATH="$CERTIFICATE_PATH" python3 -c 'import base64, os, pathlib; pathlib.Path(os.environ["CERTIFICATE_PATH"]).write_bytes(base64.b64decode(os.environ["APPLE_CERTIFICATE"], validate=True))'

security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
security set-keychain-settings -lut 21600 "$KEYCHAIN_PATH"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
security import "$CERTIFICATE_PATH" -k "$KEYCHAIN_PATH" -P "$APPLE_CERTIFICATE_PASSWORD" -T /usr/bin/codesign
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
security list-keychains -d user -s "$KEYCHAIN_PATH"

IDENTITY="$(security find-identity -v -p codesigning "$KEYCHAIN_PATH" | sed -n 's/.*"\(Developer ID Application:[^"]*\)".*/\1/p' | head -1)"
if [ -z "$IDENTITY" ]; then
  echo "Developer ID Application identity not found." >&2
  exit 1
fi

if [ -n "${GITHUB_ENV:-}" ]; then
  echo "APPLE_SIGNING_IDENTITY=$IDENTITY" >> "$GITHUB_ENV"
  echo "ENISHI_KEYCHAIN_PATH=$KEYCHAIN_PATH" >> "$GITHUB_ENV"
else
  echo "APPLE_SIGNING_IDENTITY=$IDENTITY"
  echo "ENISHI_KEYCHAIN_PATH=$KEYCHAIN_PATH"
fi
