use std::fs;
use std::io;
use std::net::TcpListener;
use std::net::{IpAddr, Ipv4Addr, SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::time::Duration;

use rand::distributions::Alphanumeric;
use rand::Rng;
use serde::Deserialize;

const TOKEN_LENGTH: usize = 48;
const KEYRING_SERVICE: &str = "com.enishi.desktop";

#[derive(Deserialize)]
struct CoreInfo {
    port: u16,
    pid: u32,
    owner: String,
}

fn core_info_path() -> Option<PathBuf> {
    if let Ok(path) = std::env::var("ENISHI_CORE_INFO_PATH") {
        return Some(PathBuf::from(path));
    }
    let home = std::env::var("HOME").ok()?;
    Some(PathBuf::from(home).join("Library/Application Support/ENISHI/core.json"))
}

pub fn load_managed_core(path: &std::path::Path) -> Option<u32> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;

        if fs::metadata(path).ok()?.permissions().mode() & 0o077 != 0 {
            return None;
        }
    }
    let payload: CoreInfo = serde_json::from_slice(&fs::read(path).ok()?).ok()?;
    if payload.pid == 0 || !matches!(payload.owner.as_str(), "headless" | "desktop") {
        return None;
    }
    let address = SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), payload.port);
    TcpStream::connect_timeout(&address, Duration::from_millis(500)).ok()?;
    Some(payload.pid)
}

pub fn stop_managed_core() {
    let Some(path) = core_info_path() else {
        return;
    };
    let Some(pid) = load_managed_core(&path) else {
        return;
    };
    let pid_argument = pid.to_string();
    let _ = Command::new("kill")
        .args(["-TERM", pid_argument.as_str()])
        .status();
    for _ in 0..30 {
        if !path.exists() {
            return;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
}

/// 127.0.0.1で利用可能なランダムポートを確保する（enishi.md §10）。
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
/// 開発時はリポジトリ相対、ENISHI_CORE_DIRで上書き可能。
pub fn core_directory() -> PathBuf {
    if let Ok(dir) = std::env::var("ENISHI_CORE_DIR") {
        return PathBuf::from(dir);
    }
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../services/local-core")
}

/// TauriのexternalBinは配布時にメイン実行ファイルと同じディレクトリへ
/// ターゲットsuffixなしの名前で配置される。
fn bundled_core_binary() -> Option<PathBuf> {
    let configured = std::env::var("ENISHI_CORE_BINARY").ok().map(PathBuf::from);
    if configured.as_ref().is_some_and(|path| path.is_file()) {
        return configured;
    }

    let executable = std::env::current_exe().ok()?;
    let candidate = executable.parent()?.join("enishi-core");
    candidate.is_file().then_some(candidate)
}

/// 実行コマンドを構築する。シェル文字列は使わず、
/// コマンド名と引数を配列で分離する（enishi.md §11, §23）。
pub fn build_core_command(port: u16) -> (String, Vec<String>) {
    if let Some(sidecar) = bundled_core_binary() {
        return (
            sidecar.to_string_lossy().into_owned(),
            vec!["--port".to_string(), port.to_string()],
        );
    }

    let configured_python = std::env::var("ENISHI_PYTHON").ok().map(PathBuf::from);
    let repository_python = core_directory().join("../../.venv/bin/python");
    let python = configured_python
        .or_else(|| repository_python.is_file().then_some(repository_python));
    let (program, mut args) = if let Some(python) = python {
        (
            python.to_string_lossy().into_owned(),
            vec!["-m".to_string(), "uvicorn".to_string()],
        )
    } else {
        (
            "uv".to_string(),
            vec!["run".to_string(), "uvicorn".to_string()],
        )
    };
    args.extend([
        "enishi_core.main:app".to_string(),
        "--host".to_string(),
        "127.0.0.1".to_string(),
        "--port".to_string(),
        port.to_string(),
    ]);
    (program, args)
}

/// Local Coreを子プロセスとして起動する。
pub fn spawn_core(port: u16, token: &str) -> io::Result<Child> {
    let (program, args) = build_core_command(port);
    let mut command = Command::new(program);
    command.args(args);
    // PyInstallerサイドカーは自己完結。開発用Pythonだけパッケージdirをcwdにする。
    if bundled_core_binary().is_none() {
        command.current_dir(core_directory());
    }
    command
        .env("ENISHI_LOCAL_TOKEN", token)
        .env("ENISHI_LOCAL_PORT", port.to_string())
        .env("ENISHI_CORE_OWNER", "desktop")
        // Tauri起動時はノード署名鍵をmacOS Keychainへ保存する。
        // CLIデモはこの環境変数を持たないため0600ファイルを使う。
        .env("ENISHI_KEYRING_SERVICE", KEYRING_SERVICE)
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
        assert!(
            program == "uv" || program.ends_with("/python") || program.ends_with("enishi-core")
        );
        if !program.ends_with("enishi-core") {
            assert!(args.contains(&"uvicorn".to_string()));
            assert!(args.contains(&"127.0.0.1".to_string()));
        }
        assert!(args.contains(&"4321".to_string()));
        // 0.0.0.0での待ち受けを禁止（enishi.md §10）
        assert!(!args.iter().any(|a| a.contains("0.0.0.0")));
    }

    #[test]
    fn core_directory_points_to_local_core() {
        let dir = core_directory();
        assert!(dir.ends_with("services/local-core") || dir.to_string_lossy().contains("local-core"));
    }

    #[test]
    fn invalid_core_info_is_not_reused() {
        let path = std::env::temp_dir().join(format!(
            "enishi-invalid-core-{}.json",
            generate_token()
        ));
        fs::write(&path, br#"{"port":8765,"pid":0,"owner":"headless"}"#).expect("write");
        assert!(load_managed_core(&path).is_none());
        let _ = fs::remove_file(path);
    }

    #[test]
    fn private_live_headless_core_is_detected() {
        #[cfg(unix)]
        use std::os::unix::fs::PermissionsExt;

        let listener = TcpListener::bind(("127.0.0.1", 0)).expect("listen");
        let port = listener.local_addr().expect("address").port();
        let path = std::env::temp_dir().join(format!(
            "enishi-live-core-{}.json",
            generate_token()
        ));
        fs::write(
            &path,
            format!(r#"{{"port":{port},"pid":{},"owner":"headless"}}"#, std::process::id()),
        )
        .expect("write");
        #[cfg(unix)]
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).expect("chmod");
        let pid = load_managed_core(&path).expect("pid");
        assert_eq!(pid, std::process::id());
        let _ = fs::remove_file(path);
    }

    #[test]
    fn private_live_desktop_core_is_detected_for_handoff() {
        #[cfg(unix)]
        use std::os::unix::fs::PermissionsExt;

        let listener = TcpListener::bind(("127.0.0.1", 0)).expect("listen");
        let port = listener.local_addr().expect("address").port();
        let path = std::env::temp_dir().join(format!(
            "enishi-live-desktop-core-{}.json",
            generate_token()
        ));
        fs::write(
            &path,
            format!(r#"{{"port":{port},"pid":{},"owner":"desktop"}}"#, std::process::id()),
        )
        .expect("write");
        #[cfg(unix)]
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).expect("chmod");
        let pid = load_managed_core(&path).expect("pid");
        assert_eq!(pid, std::process::id());
        let _ = fs::remove_file(path);
    }
}
