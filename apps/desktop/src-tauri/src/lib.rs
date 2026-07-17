pub mod commands;
pub mod process;
pub mod state;

use state::{AppState, CoreConnection};

pub fn run() {
    // Codexが起動した限定権限のheadless Coreを止め、同じDBをUI所有Coreへ引き継ぐ。
    process::stop_headless_core();
    let port = process::pick_free_port().expect("no free local port available");
    let token = process::generate_token();
    // Local Coreを起動する。失敗してもUIは表示し、画面側で未接続を示す。
    let child = match process::spawn_core(port, &token) {
        Ok(child) => Some(child),
        Err(error) => {
            eprintln!("failed to start enishi-core: {error}");
            None
        }
    };

    let app_state = AppState::new(CoreConnection { port, token }, child);

    tauri::Builder::default()
        .manage(app_state)
        .invoke_handler(tauri::generate_handler![commands::get_core_connection])
        .build(tauri::generate_context!())
        .expect("error while building ENISHI")
        .run(|app_handle, event| {
            // アプリ終了時にLocal Coreも終了させ、孤立プロセスを残さない（enishi.md §10）
            if let tauri::RunEvent::Exit = event {
                use tauri::Manager;
                if let Some(state) = app_handle.try_state::<AppState>() {
                    state.shutdown();
                }
            }
        });
}
