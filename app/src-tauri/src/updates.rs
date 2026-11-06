//! Desktop updates, checked against the MOTH Cloud server the user is connected to.
//!
//! The update endpoint follows the server URL configured in the app (Settings → Connection), so a
//! changed server address never needs a rebuild. Every update is verified by the Tauri updater
//! against the public key built into the app (and, with `requireSignedVersion`, the signed version
//! must match the offered one, which blocks downgrade attacks). Installing stops the local backend
//! first so the Windows installer can replace its files.

use std::sync::Mutex;
use std::time::Duration;

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager, State, Url};
use tauri_plugin_updater::{Update, UpdaterExt};

use crate::Backend;

/// Appends to `<app data>/logs/updates.log` (kept small): what the updater did and why, for support.
pub fn log_line(app: &AppHandle, msg: &str) {
    use std::io::Write;
    if let Ok(dir) = app.path().app_data_dir() {
        let dir = dir.join("logs");
        let _ = std::fs::create_dir_all(&dir);
        let path = dir.join("updates.log");
        if std::fs::metadata(&path).map(|m| m.len() > 1_000_000).unwrap_or(false) {
            let _ = std::fs::rename(&path, dir.join("updates.log.1"));
        }
        if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(&path) {
            let ts = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_secs())
                .unwrap_or(0);
            let _ = writeln!(f, "{ts} {msg}");
        }
    }
}

#[tauri::command]
pub fn update_log(app: AppHandle, message: String) {
    log_line(&app, &format!("[app] {}", message.chars().take(500).collect::<String>()));
}

#[derive(Default)]
pub struct PendingUpdate {
    update: Mutex<Option<Update>>,
    bytes: Mutex<Option<Vec<u8>>>,
}

#[derive(Serialize, Clone)]
pub struct UpdateInfo {
    version: String,
    current_version: String,
    notes: Option<String>,
}

#[derive(Serialize, Clone)]
struct Progress {
    downloaded: u64,
    total: Option<u64>,
}

/// The update endpoint for a MOTH Cloud server address (http only for loopback test servers).
pub fn endpoint_for(server: &str, channel: &str) -> Result<Url, String> {
    let base = server.trim().trim_end_matches('/');
    let url = Url::parse(&format!(
        "{base}/v1/updates/desktop/{{{{target}}}}/{{{{arch}}}}/{{{{current_version}}}}?channel={channel}"
    ))
    .map_err(|e| format!("invalid MOTH Cloud address: {e}"))?;
    match url.scheme() {
        "https" => Ok(url),
        "http" if matches!(url.host_str(), Some("127.0.0.1") | Some("localhost")) => Ok(url),
        _ => Err("updates are only downloaded over HTTPS".into()),
    }
}

#[tauri::command]
pub async fn update_check(
    app: AppHandle,
    state: State<'_, PendingUpdate>,
    server: String,
    install_id: String,
    channel: Option<String>,
) -> Result<Option<UpdateInfo>, String> {
    log_line(&app, &format!("check {server} (current {})", app.package_info().version));
    let endpoint = endpoint_for(&server, channel.as_deref().unwrap_or("stable")).map_err(|e| {
        log_line(&app, &format!("check refused: {e}"));
        e
    })?;
    let updater = app
        .updater_builder()
        .endpoints(vec![endpoint])
        .map_err(|e| e.to_string())?
        .header("X-Moth-Install-Id", install_id)
        .map_err(|e| e.to_string())?
        .header("X-Moth-Client", format!("desktop/{}", app.package_info().version))
        .map_err(|e| e.to_string())?
        .timeout(Duration::from_secs(60))
        .build()
        .map_err(|e| e.to_string())?;
    let found = updater.check().await.map_err(|e| {
        log_line(&app, &format!("check failed: {e}"));
        e.to_string()
    })?;
    log_line(&app, &match &found {
        Some(u) => format!("update available: {}", u.version),
        None => "up to date".to_string(),
    });
    let info = found.as_ref().map(|u| UpdateInfo {
        version: u.version.clone(),
        current_version: u.current_version.clone(),
        notes: u.body.clone(),
    });
    *state.update.lock().unwrap() = found;
    *state.bytes.lock().unwrap() = None;
    Ok(info)
}

/// Download (and signature-verify) the pending update; progress is emitted as `moth-update-progress`.
#[tauri::command]
pub async fn update_download(app: AppHandle, state: State<'_, PendingUpdate>) -> Result<(), String> {
    let update = state.update.lock().unwrap().clone().ok_or("no update is pending")?;
    let mut downloaded: u64 = 0;
    let handle = app.clone();
    let bytes = update
        .download(
            move |chunk, total| {
                downloaded += chunk as u64;
                let _ = handle.emit("moth-update-progress", Progress { downloaded, total });
            },
            || {},
        )
        .await
        .map_err(|e| {
            log_line(&app, &format!("download failed: {e}"));
            e.to_string()
        })?;
    log_line(&app, &format!("downloaded and verified {} ({} bytes)", update.version, bytes.len()));
    *state.bytes.lock().unwrap() = Some(bytes);
    Ok(())
}

/// Install the downloaded update. On Windows the installer starts and MOTH Code exits.
#[tauri::command]
pub fn update_install(app: AppHandle, state: State<'_, PendingUpdate>) -> Result<(), String> {
    let update = state.update.lock().unwrap().clone().ok_or("no update is pending")?;
    let bytes = state.bytes.lock().unwrap().take().ok_or("the update has not been downloaded")?;
    log_line(&app, &format!("installing {}", update.version));
    app.state::<Backend>().stop(); // release the backend's files before the installer replaces them
    update.install(bytes).map_err(|e| {
        log_line(&app, &format!("install failed: {e}"));
        e.to_string()
    })
}

#[cfg(test)]
mod tests {
    use super::endpoint_for;

    #[test]
    fn endpoint_follows_the_configured_server() {
        let u = endpoint_for("https://moth.example.com/", "stable").unwrap();
        assert_eq!(
            u.as_str(),
            "https://moth.example.com/v1/updates/desktop/%7B%7Btarget%7D%7D/%7B%7Barch%7D%7D/%7B%7Bcurrent_version%7D%7D?channel=stable"
        );
        assert!(endpoint_for("http://127.0.0.1:8900", "beta").is_ok());
        assert!(endpoint_for("http://moth.example.com", "stable").is_err());
        assert!(endpoint_for("not a url", "stable").is_err());
    }
}
