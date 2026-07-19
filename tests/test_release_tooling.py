"""macOS配布スクリプトのfail-closed契約を検証する。"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(
    script: str, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *args],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_release_config_requires_key_and_https(tmp_path: Path) -> None:
    output = tmp_path / "release.json"
    env = os.environ.copy()
    env.pop("TAURI_UPDATER_PUBLIC_KEY", None)
    result = _run("create_macos_release_config.py", "--output", str(output), env=env)
    assert result.returncode != 0
    assert "TAURI_UPDATER_PUBLIC_KEY is required" in result.stderr

    env["TAURI_UPDATER_PUBLIC_KEY"] = "trusted-public-key"
    result = _run(
        "create_macos_release_config.py",
        "--output",
        str(output),
        "--endpoint",
        "http://updates.example.test/latest.json",
        env=env,
    )
    assert result.returncode != 0
    assert "must use HTTPS" in result.stderr


def test_release_config_enables_signed_updater_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "release.json"
    env = {**os.environ, "TAURI_UPDATER_PUBLIC_KEY": "trusted-public-key"}
    result = _run("create_macos_release_config.py", "--output", str(output), env=env)
    assert result.returncode == 0, result.stderr

    config = json.loads(output.read_text())
    assert config["bundle"]["createUpdaterArtifacts"] is True
    assert config["plugins"]["updater"]["pubkey"] == "trusted-public-key"
    assert config["plugins"]["updater"]["endpoints"] == [
        "https://github.com/Maaa2005/ENISHI/releases/latest/download/latest.json"
    ]
    assert output.stat().st_mode & 0o777 == 0o600


def test_updater_manifest_binds_tag_artifact_and_signature(tmp_path: Path) -> None:
    artifact = tmp_path / "ENISHI.app.tar.gz"
    signature = tmp_path / "ENISHI.app.tar.gz.sig"
    output = tmp_path / "latest.json"
    artifact.write_bytes(b"archive")
    signature.write_text("signed-value\n")

    mismatch = _run(
        "generate_updater_manifest.py",
        "--version",
        "1.2.3",
        "--tag",
        "v1.2.4",
        "--artifact",
        str(artifact),
        "--signature",
        str(signature),
        "--output",
        str(output),
    )
    assert mismatch.returncode != 0
    assert "tag/version mismatch" in mismatch.stderr

    result = _run(
        "generate_updater_manifest.py",
        "--version",
        "1.2.3",
        "--tag",
        "v1.2.3",
        "--artifact",
        str(artifact),
        "--signature",
        str(signature),
        "--output",
        str(output),
    )
    assert result.returncode == 0, result.stderr
    manifest = json.loads(output.read_text())
    platform = next(iter(manifest["platforms"].values()))
    assert manifest["version"] == "1.2.3"
    assert platform["signature"] == "signed-value"
    assert platform["url"].endswith("/v1.2.3/ENISHI.app.tar.gz")
