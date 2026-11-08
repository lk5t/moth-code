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
    if !matches!(channel, "stable" | "beta") {
        return Err("unknown desktop update channel".into());
    }
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

// Request metadata ourselves so HTTP errors retain the server's explanation. The updater's
// check() collapses HTTP failures into ReleaseNotFound. restore_update() retains Tauri's version
// comparison, platform selection and mandatory signed-version verification for the actual package.
async fn check_metadata(endpoint: Url, install_id: &str, version: &str) -> Result<Option<serde_json::Value>, String> {
    let response = reqwest::Client::builder()
        .timeout(Duration::from_secs(60))
        .build().map_err(|e| e.to_string())?
        .get(endpoint)
        .header("Accept", "application/json")
        .header("Cache-Control", "no-cache, no-store")
        .header("Pragma", "no-cache")
        .header("X-Moth-Install-Id", install_id)
        .header("X-Moth-Client", format!("desktop/{version}"))
        .send().await.map_err(|e| e.to_string())?;
    let status = response.status();
    if status == reqwest::StatusCode::NO_CONTENT {
        return Ok(None);
    }
    if !status.is_success() {
        let detail = response.json::<serde_json::Value>().await.ok()
            .and_then(|v| v.get("detail").and_then(|s| s.as_str()).map(str::to_owned))
            .unwrap_or_else(|| "MOTH Cloud did not return valid desktop update metadata. Check the server address and release relay.".into());
        return Err(format!("Update check failed (HTTP {status}): {detail}"));
    }
    response.json().await.map(Some).map_err(|e| format!("Invalid desktop update metadata: {e}"))
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
    let version = app.package_info().version.to_string();
    let target = std::env::consts::OS;
    let endpoint = Url::parse(&endpoint.to_string()
        .replace("%7B%7Btarget%7D%7D", if target == "macos" { "darwin" } else { target })
        .replace("%7B%7Barch%7D%7D", std::env::consts::ARCH)
        .replace("%7B%7Bcurrent_version%7D%7D", &version)).map_err(|e| e.to_string())?;
    let updater = app
        .updater_builder()
        .endpoints(vec![endpoint.clone()])
        .map_err(|e| e.to_string())?
        .header("X-Moth-Install-Id", install_id.clone())
        .map_err(|e| e.to_string())?
        .header("X-Moth-Client", format!("desktop/{}", app.package_info().version))
        .map_err(|e| e.to_string())?
        .timeout(Duration::from_secs(60))
        .build()
        .map_err(|e| e.to_string())?;
    let found = match check_metadata(endpoint, &install_id, &version).await {
        Ok(Some(metadata)) => updater.restore_update(metadata).map_err(|e| e.to_string()),
        Ok(None) => Ok(None),
        Err(e) => Err(e),
    }.map_err(|e| {
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
    use super::{check_metadata, endpoint_for};

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
        assert!(endpoint_for("https://moth.example.com", "stable&unsafe=true").is_err());
    }

    fn metadata_response(status: &str, body: &str) -> Result<Option<serde_json::Value>, String> {
        use std::io::{Read, Write};
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}/v1/updates/desktop/windows/x86_64/0.5.1", listener.local_addr().unwrap());
        let response = format!("HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len());
        let thread = std::thread::spawn(move || {
            let (mut socket, _) = listener.accept().unwrap();
            socket.set_read_timeout(Some(std::time::Duration::from_secs(10))).unwrap();
            let mut bytes = Vec::new();
            while !bytes.ends_with(b"\r\n\r\n") {
                let mut b = [0; 1];
                socket.read_exact(&mut b).unwrap();
                bytes.push(b[0]);
            }
            let request = String::from_utf8(bytes).unwrap().to_lowercase();
            assert!(request.contains("x-moth-client: desktop/0.5.1"));
            assert!(request.contains("cache-control: no-cache, no-store"));
            socket.write_all(response.as_bytes()).unwrap();
        });
        let result = tauri::async_runtime::block_on(check_metadata(url.parse().unwrap(), "test-install", "0.5.1"));
        thread.join().unwrap();
        result
    }

    #[test]
    fn metadata_detection_051_to_054_and_genuine_no_update() {
        let found = metadata_response("200 OK", r#"{"version":"0.5.4","url":"https://moth.example/setup.exe","signature":"signed"}"#).unwrap().unwrap();
        assert_eq!(found["version"], "0.5.4");
        assert!(metadata_response("204 No Content", "").unwrap().is_none());
    }

    #[test]
    fn metadata_errors_are_not_no_update() {
        for status in ["403 Forbidden", "404 Not Found", "409 Conflict", "503 Service Unavailable"] {
            let err = metadata_response(status, r#"{"detail":"Desktop 0.5.4 installer is not available"}"#).unwrap_err();
            assert!(err.contains(status));
            assert!(err.contains("Desktop 0.5.4 installer is not available"));
        }
        assert!(metadata_response("200 OK", "not JSON").unwrap_err().contains("Invalid desktop update metadata"));
        assert!(metadata_response("502 Bad Gateway", "<html>proxy error</html>").unwrap_err().contains("HTTP 502"));
    }
}
