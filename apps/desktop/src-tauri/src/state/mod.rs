use std::process::Child;
use std::sync::Mutex;

use serde::Serialize;

/// フロントエンドへ渡すLocal Core接続情報。
/// トークンは起動ごとに生成されるプロセス寿命限定の値。
#[derive(Clone, Serialize)]
pub struct CoreConnection {
    pub port: u16,
    pub token: String,
}

pub struct AppState {
    pub connection: CoreConnection,
    child: Mutex<Option<Child>>,
}

impl AppState {
    pub fn new(connection: CoreConnection, child: Option<Child>) -> Self {
        Self {
            connection,
            child: Mutex::new(child),
        }
    }

    /// Local Coreプロセスを終了させる。二重呼び出しは無害。
    pub fn shutdown(&self) {
        if let Ok(mut guard) = self.child.lock() {
            if let Some(mut child) = guard.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

impl Drop for AppState {
    fn drop(&mut self) {
        self.shutdown();
    }
}
