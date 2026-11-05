mod backend;
mod credentials;

use backend::{Backend, BackendInfo};
use credentials::{AccountsFile, AccountsStore, OsVault, SavedAccount};
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

fn accounts_store(app: &tauri::AppHandle) -> Result<AccountsStore, String> {
    let dir = app.path().app_config_dir().map_err(|e| e.to_string())?;
    Ok(AccountsStore { path: dir.join("accounts.json") })
}

#[tauri::command]
fn accounts_load(app: tauri::AppHandle) -> Result<AccountsFile, String> {
    Ok(accounts_store(&app)?.load())
}

/// Remember an account; the token goes to the OS credential vault.
#[tauri::command]
fn accounts_remember(app: tauri::AppHandle, account: SavedAccount, token: String) -> Result<AccountsFile, String> {
    accounts_store(&app)?.remember(&OsVault, account, &token)
}

/// Make an account active and return its stored token (None if it was signed out).
#[tauri::command]
fn accounts_activate(app: tauri::AppHandle, key: String) -> Result<Option<String>, String> {
    accounts_store(&app)?.activate(&OsVault, &key)
}

#[tauri::command]
fn accounts_sign_out(app: tauri::AppHandle, key: String) -> Result<AccountsFile, String> {
    accounts_store(&app)?.sign_out(&OsVault, &key)
}

#[tauri::command]
fn accounts_forget(app: tauri::AppHandle, key: String) -> Result<AccountsFile, String> {
    accounts_store(&app)?.forget(&OsVault, &key)
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(Backend::new())
        .setup(|app| {
            let resource_dir = app.path().resource_dir().ok();
            app.state::<Backend>().start(resource_dir);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            backend_info,
            restart_backend,
            accounts_load,
            accounts_remember,
            accounts_activate,
            accounts_sign_out,
            accounts_forget
        ])
        .build(tauri::generate_context!())
        .expect("error while building MOTH Code");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            handle.state::<Backend>().stop();
        }
    });
}
