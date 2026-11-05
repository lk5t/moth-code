mod backend;

use backend::{Backend, BackendInfo};
use tauri::{Manager, RunEvent};

#[tauri::command]
fn backend_info(state: tauri::State<'_, Backend>) -> BackendInfo {
    state.snapshot()
}

#[tauri::command]
fn restart_backend(app: tauri::AppHandle, state: tauri::State<'_, Backend>) {
    state.stop();
    state.start(app.path().resource_dir().ok());
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_process::init())
        .manage(Backend::new())
        .setup(|app| {
            let resource_dir = app.path().resource_dir().ok();
            app.state::<Backend>().start(resource_dir);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![backend_info, restart_backend])
        .build(tauri::generate_context!())
        .expect("error while building MOTH Code");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            handle.state::<Backend>().stop();
        }
    });
}
