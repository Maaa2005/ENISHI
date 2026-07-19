# macOS release operations

ENISHI releases are built only from a `v*` tag by `.github/workflows/release.yml`.
The workflow recursively signs the app and bundled Local Core with the same
Developer ID identity, submits the result for Apple notarization, verifies the
stapled ticket, signs the updater archive with Tauri's Minisign-compatible key,
and publishes the DMG, updater archive, signature, and `latest.json` together.

## One-time setup

Create a GitHub `release` environment with an approval rule. Add these secrets:

- `APPLE_CERTIFICATE`: base64-encoded Developer ID Application `.p12`
- `APPLE_CERTIFICATE_PASSWORD`
- `KEYCHAIN_PASSWORD`: random password used only for the temporary CI keychain
- `APPLE_ID`, `APPLE_PASSWORD`, `APPLE_TEAM_ID`: Apple notarization credentials
- `TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`: updater key

Add `TAURI_UPDATER_PUBLIC_KEY` as an environment variable, not a secret. It is
embedded in the app and must match the private updater key. Generate the keypair
once with Tauri CLI and store the private key in an offline backup; losing it
prevents updates to already installed copies.

Never place the `.p12`, Apple password, or updater private key in `.env`, the
repository, workflow artifacts, logs, or the Vault.

## Release

Keep the version in `apps/desktop/src-tauri/tauri.conf.json` equal to the tag:

```bash
git tag -s v0.1.0 -m "ENISHI v0.1.0"
git push origin v0.1.0
```

The release fails closed when the tag and app version differ, when any signing
credential is absent, when the updater endpoint is not HTTPS, when nested code
signatures fail, or when the notarization ticket is not stapled. Installation
remains a human action in the desktop UI: check, review the version, then choose
**更新して再起動**.
