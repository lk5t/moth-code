mod backend;
mod credentials;
mod updates;

pub(crate) use backend::{Backend, BackendInfo};
use credentials::{AccountsFile, AccountsStore, OsVault, SavedAccount};
use std::sync::atomic::{AtomicBool, Ordering};
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{Manager, RunEvent, WindowEvent};

/// 0.10.0: closing the window keeps MOTH Code running in the tray (so alerts still arrive) unless the
/// user turned it off; "Quit MOTH Code" in the tray menu really exits.
struct Tray {
    keep_running: AtomicBool,
    quitting: AtomicBool,
}

#[tauri::command]
fn tray_keep_running(state: tauri::State<'_, Tray>, enabled: bool) {
    state.keep_running.store(enabled, Ordering::Relaxed);
}

#[tauri::command]
fn tray_set_status(app: tauri::AppHandle, text: String) {
    if let Some(tray) = app.tray_by_id("moth") {
        let _ = tray.set_tooltip(Some(text.chars().take(120).collect::<String>()));
    }
}

fn show_main(app: &tauri::AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.unminimize();
        let _ = w.set_focus();
    }
}

fn build_tray(app: &tauri::App) -> tauri::Result<()> {
    let show = MenuItem::with_id(app, "show", "Open MOTH Code", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit MOTH Code", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show, &quit])?;
    let mut builder = TrayIconBuilder::with_id("moth")
        .tooltip("MOTH Code")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "show" => show_main(app),
            "quit" => {
                app.state::<Tray>().quitting.store(true, Ordering::Relaxed);
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = event {
                show_main(tray.app_handle());
            }
        });
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder.build(app)?;
    Ok(())
}

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
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .manage(Tray { keep_running: AtomicBool::new(true), quitting: AtomicBool::new(false) })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                let tray = window.app_handle().state::<Tray>();
                if tray.keep_running.load(Ordering::Relaxed) && !tray.quitting.load(Ordering::Relaxed)
                    && window.app_handle().tray_by_id("moth").is_some() {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .manage(Backend::new())
        .manage(updates::PendingUpdate::default())
        .setup(|app| {
            updates::log_line(app.handle(), &format!("MOTH Code {} started", app.package_info().version));
            let resource_dir = app.path().resource_dir().ok();
            app.state::<Backend>().start(resource_dir);
            if let Err(e) = build_tray(app) {
                updates::log_line(app.handle(), &format!("tray icon unavailable: {e}"));
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            backend_info,
            restart_backend,
            accounts_load,
            accounts_remember,
            accounts_activate,
            accounts_sign_out,
            accounts_forget,
            tray_keep_running,
            tray_set_status,
            updates::update_check,
            updates::update_download,
            updates::update_install,
            updates::update_log
        ])
        .build(tauri::generate_context!())
        .expect("error while building MOTH Code");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            handle.state::<Backend>().stop();
        }
    });
}
