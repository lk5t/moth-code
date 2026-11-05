//! Launches and supervises the Python backend (`moth.server`).
//!
//! Resolution order:
//! 1. `MOTH_BACKEND_URL` — connect to an already-running backend (development).
//! 2. A bundled backend executable in the app's resource directory
//!    (`backend/moth-backend[.exe]`, produced by PyInstaller in release builds).
//! 2b. `MOTH_PYTHON` — use that interpreter with `-m moth.server` (e.g. a CUDA
//!    PyTorch environment); takes precedence over the bundled backend.
//! 3. Development fallback: `python -m moth.server` from the repository's
//!    `backend/` directory.
//!
//! The backend binds an ephemeral localhost port and prints
//! `MOTH_BACKEND_READY {"port": N}`; a random per-launch token is required on
//! every API request so other local processes cannot drive the agent.

use serde::Serialize;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;

#[derive(Clone, Serialize, Debug, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum Status {
    Starting,
    Ready,
    Failed,
}

#[derive(Clone, Serialize, Debug)]
pub struct BackendInfo {
    pub status: Status,
    pub url: String,
    pub token: String,
    pub error: Option<String>,
    pub logs: Vec<String>,
}

pub struct Backend {
    pub info: Arc<Mutex<BackendInfo>>,
    child: Arc<Mutex<Option<Child>>>,
}

pub fn random_token() -> String {
    let mut buf = [0u8; 24];
    getrandom::fill(&mut buf).expect("OS randomness unavailable");
    buf.iter().map(|b| format!("{b:02x}")).collect()
}

/// Parse the readiness line printed by the backend. Returns the port.
pub fn parse_ready_line(line: &str) -> Option<u16> {
    let rest = line.trim().strip_prefix("MOTH_BACKEND_READY ")?;
    let v: serde_json::Value = serde_json::from_str(rest).ok()?;
    v.get("port")?.as_u64().and_then(|p| u16::try_from(p).ok())
}

fn push_log(info: &Arc<Mutex<BackendInfo>>, line: String) {
    let mut i = info.lock().unwrap();
    i.logs.push(line);
    let n = i.logs.len();
    if n > 200 {
        i.logs.drain(0..n - 200);
    }
}

impl Backend {
    pub fn new() -> Self {
        Backend {
            info: Arc::new(Mutex::new(BackendInfo {
                status: Status::Starting,
                url: String::new(),
                token: String::new(),
                error: None,
                logs: vec![],
            })),
            child: Arc::new(Mutex::new(None)),
        }
    }

    pub fn snapshot(&self) -> BackendInfo {
        self.info.lock().unwrap().clone()
    }

    fn command(resource_dir: Option<&Path>) -> Result<Command, String> {
        // Explicit interpreter override, e.g. a Python environment with CUDA-enabled PyTorch
        // and `pip install ./backend`. Takes precedence over the bundled CPU backend.
        if let Ok(python) = std::env::var("MOTH_PYTHON") {
            let mut c = Command::new(python);
            c.args(["-m", "moth.server"]);
            let dev_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../backend");
            if dev_dir.join("moth").exists() {
                c.current_dir(dev_dir);
            }
            return Ok(c);
        }
        let exe_name = if cfg!(windows) { "moth-backend.exe" } else { "moth-backend" };
        if let Some(dir) = resource_dir {
            let bundled = dir.join("backend").join(exe_name);
            if bundled.exists() {
                let mut c = Command::new(&bundled);
                c.current_dir(dir.join("backend"));
                return Ok(c);
            }
        }
        // Development fallback.
        let backend_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../backend");
        if !backend_dir.join("moth").exists() {
            return Err(format!(
                "No bundled backend found and the development backend directory {} does not exist.",
                backend_dir.display()
            ));
        }
        let python = if cfg!(windows) { "python" } else { "python3" };
        let mut c = Command::new(python);
        c.args(["-m", "moth.server"]).current_dir(backend_dir);
        Ok(c)
    }

    pub fn start(&self, resource_dir: Option<PathBuf>) {
        {
            let mut i = self.info.lock().unwrap();
            i.status = Status::Starting;
            i.error = None;
            i.logs.clear();
        }
        if let Ok(url) = std::env::var("MOTH_BACKEND_URL") {
            let mut i = self.info.lock().unwrap();
            i.url = url;
            i.token = std::env::var("MOTH_API_TOKEN").unwrap_or_default();
            i.status = Status::Ready;
            return;
        }
        let token = random_token();
        let mut cmd = match Self::command(resource_dir.as_deref()) {
            Ok(c) => c,
            Err(e) => {
                let mut i = self.info.lock().unwrap();
                i.status = Status::Failed;
                i.error = Some(e);
                return;
            }
        };
        cmd.env("MOTH_API_TOKEN", &token)
            .env("MOTH_PORT", "0")
            .env("MOTH_PARENT_PID", std::process::id().to_string())
            .env("PYTHONUNBUFFERED", "1")
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }
        let mut child = match cmd.spawn() {
            Ok(c) => c,
            Err(e) => {
                let mut i = self.info.lock().unwrap();
                i.status = Status::Failed;
                i.error = Some(format!(
                    "Could not start the MOTH backend: {e}. In development, install Python 3.10+ and run \
                     `pip install -e backend` (or set MOTH_PYTHON)."
                ));
                return;
            }
        };
        let stdout = child.stdout.take();
        let stderr = child.stderr.take();
        *self.child.lock().unwrap() = Some(child);

        if let Some(out) = stdout {
            let info = self.info.clone();
            let token = token.clone();
            thread::spawn(move || {
                for line in BufReader::new(out).lines().map_while(Result::ok) {
                    if let Some(port) = parse_ready_line(&line) {
                        let mut i = info.lock().unwrap();
                        i.url = format!("http://127.0.0.1:{port}");
                        i.token = token.clone();
                        i.status = Status::Ready;
                    } else {
                        push_log(&info, line);
                    }
                }
            });
        }
        if let Some(err) = stderr {
            let info = self.info.clone();
            thread::spawn(move || {
                for line in BufReader::new(err).lines().map_while(Result::ok) {
                    push_log(&info, line);
                }
            });
        }
        // Watch for early exit (crash during startup or later).
        let info = self.info.clone();
        let child = self.child.clone();
        thread::spawn(move || loop {
            thread::sleep(std::time::Duration::from_millis(500));
            let mut guard = child.lock().unwrap();
            match guard.as_mut().map(|c| c.try_wait()) {
                Some(Ok(Some(status))) => {
                    let mut i = info.lock().unwrap();
                    i.status = Status::Failed;
                    i.error = Some(format!("The MOTH backend exited unexpectedly ({status})."));
                    *guard = None;
                    return;
                }
                Some(Ok(None)) => continue,
                _ => return, // stopped intentionally or error
            }
        });
    }

    pub fn stop(&self) {
        if let Some(mut child) = self.child.lock().unwrap().take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_ready_line() {
        assert_eq!(parse_ready_line("MOTH_BACKEND_READY {\"port\": 51234, \"home\": \"x\"}"), Some(51234));
        assert_eq!(parse_ready_line("something else"), None);
        assert_eq!(parse_ready_line("MOTH_BACKEND_READY {\"port\": 99999}"), None);
    }

    #[test]
    fn token_is_random_hex() {
        let a = random_token();
        let b = random_token();
        assert_eq!(a.len(), 48);
        assert_ne!(a, b);
        assert!(a.chars().all(|c| c.is_ascii_hexdigit()));
    }
}
