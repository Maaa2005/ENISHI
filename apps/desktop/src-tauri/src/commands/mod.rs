use tauri::State;

use crate::state::{AppState, CoreConnection};

/// フロントエンドへLocal Coreの接続先（ポートとトークン）を返す。
/// Keychain対象の永続秘密情報は扱わない（twinlink.md §9）。
#[tauri::command]
pub fn get_core_connection(state: State<'_, AppState>) -> CoreConnection {
    state.connection.clone()
}
