use std::io;
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};

use rand::distributions::Alphanumeric;
use rand::Rng;

const TOKEN_LENGTH: usize = 48;
const KEYRING_SERVICE: &str = "com.twinlink.desktop";

/// 127.0.0.1で利用可能なランダムポートを確保する（twinlink.md §10）。
pub fn pick_free_port() -> io::Result<u16> {
    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    Ok(listener.local_addr()?.port())
}

/// 起動ごとのローカル認証トークンを生成する。
pub fn generate_token() -> String {
    rand::thread_rng()
        .sample_iter(&Alphanumeric)
        .take(TOKEN_LENGTH)
        .map(char::from)
        .collect()
}

/// Local Coreのパッケージディレクトリ（services/local-core）。
/// 開発時はリポジトリ相対、TWINLINK_CORE_DIRで上書き可能。
pub fn core_directory() -> PathBuf {
    if let Ok(dir) = std::env::var("TWINLINK_CORE_DIR") {
        return PathBuf::from(dir);
    }
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../services/local-core")
}

/// 実行コマンドを構築する。シェル文字列は使わず、
/// コマンド名と引数を配列で分離する（twinlink.md §11, §23）。
pub fn build_core_command(port: u16) -> (String, Vec<String>) {
    let program = "uv".to_string();
    let args = vec![
        "run".to_string(),
        "uvicorn".to_string(),
        "twinlink_core.main:app".to_string(),
        "--host".to_string(),
        "127.0.0.1".to_string(),
        "--port".to_string(),
        port.to_string(),
    ];
    (program, args)
}

/// Local Coreを子プロセスとして起動する。
pub fn spawn_core(port: u16, token: &str) -> io::Result<Child> {
    let (program, args) = build_core_command(port);
    Command::new(program)
        .args(args)
        .current_dir(core_directory())
        .env("TWINLINK_LOCAL_TOKEN", token)
        .env("TWINLINK_LOCAL_PORT", port.to_string())
        // Tauri起動時はノード署名鍵をmacOS Keychainへ保存する。
        // CLIデモはこの環境変数を持たないため0600ファイルを使う。
        .env("TWINLINK_KEYRING_SERVICE", KEYRING_SERVICE)
        .stdin(Stdio::null())
        .spawn()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pick_free_port_returns_nonzero() {
        let port = pick_free_port().expect("port");
        assert!(port > 0);
    }

    #[test]
    fn generate_token_is_long_and_unique() {
        let a = generate_token();
        let b = generate_token();
        assert_eq!(a.len(), TOKEN_LENGTH);
        assert_ne!(a, b);
        assert!(a.chars().all(|c| c.is_ascii_alphanumeric()));
    }

    #[test]
    fn build_core_command_binds_loopback_only() {
        let (program, args) = build_core_command(4321);
        assert_eq!(program, "uv");
        assert!(args.contains(&"127.0.0.1".to_string()));
        assert!(args.contains(&"4321".to_string()));
        // 0.0.0.0での待ち受けを禁止（twinlink.md §10）
        assert!(!args.iter().any(|a| a.contains("0.0.0.0")));
    }

    #[test]
    fn core_directory_points_to_local_core() {
        let dir = core_directory();
        assert!(dir.ends_with("services/local-core") || dir.to_string_lossy().contains("local-core"));
    }
}
