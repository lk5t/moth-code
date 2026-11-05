//! Secure storage for MOTH account session tokens and the saved-accounts list.
//!
//! * Session tokens live in the operating system's credential vault
//!   (Windows Credential Manager; macOS Keychain; Linux kernel keyring) under the
//!   service name `MOTH Code`, keyed by `<server>|<username>`.
//! * The list of saved accounts (server, username, display name, avatar URL — no secrets)
//!   is a JSON file in the app's config directory.
//! Tokens are never written to disk in plain text by MOTH Code.

use serde::{Deserialize, Serialize};
use std::path::PathBuf;

const SERVICE: &str = "MOTH Code";

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
pub struct SavedAccount {
    pub server: String,
    pub username: String,
    #[serde(default)]
    pub display_name: Option<String>,
    #[serde(default)]
    pub avatar_url: Option<String>,
    #[serde(default)]
    pub role: Option<String>,
    #[serde(default)]
    pub last_used: f64,
}

#[derive(Serialize, Deserialize, Clone, Debug, Default, PartialEq)]
pub struct AccountsFile {
    #[serde(default)]
    pub active: Option<String>, // key of the active account
    #[serde(default)]
    pub accounts: Vec<SavedAccount>,
}

pub fn account_key(server: &str, username: &str) -> String {
    format!("{}|{}", server.trim_end_matches('/'), username.to_lowercase())
}

/// Abstraction over the secret store so logic can be unit-tested without a real vault.
pub trait SecretStore {
    fn set(&self, key: &str, secret: &str) -> Result<(), String>;
    fn get(&self, key: &str) -> Result<Option<String>, String>;
    fn delete(&self, key: &str) -> Result<(), String>;
}

pub struct OsVault;

impl SecretStore for OsVault {
    fn set(&self, key: &str, secret: &str) -> Result<(), String> {
        keyring::Entry::new(SERVICE, key).and_then(|e| e.set_password(secret)).map_err(|e| e.to_string())
    }
    fn get(&self, key: &str) -> Result<Option<String>, String> {
        match keyring::Entry::new(SERVICE, key).and_then(|e| e.get_password()) {
            Ok(s) => Ok(Some(s)),
            Err(keyring::Error::NoEntry) => Ok(None),
            Err(e) => Err(e.to_string()),
        }
    }
    fn delete(&self, key: &str) -> Result<(), String> {
        match keyring::Entry::new(SERVICE, key).and_then(|e| e.delete_credential()) {
            Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
            Err(e) => Err(e.to_string()),
        }
    }
}

pub struct AccountsStore {
    pub path: PathBuf,
}

impl AccountsStore {
    pub fn load(&self) -> AccountsFile {
        std::fs::read_to_string(&self.path)
            .ok()
            .and_then(|s| serde_json::from_str(&s).ok())
            .unwrap_or_default()
    }

    pub fn save(&self, file: &AccountsFile) -> Result<(), String> {
        if let Some(dir) = self.path.parent() {
            std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
        }
        let tmp = self.path.with_extension("json.tmp");
        std::fs::write(&tmp, serde_json::to_string_pretty(file).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
        std::fs::rename(&tmp, &self.path).map_err(|e| e.to_string())
    }

    /// Save (or update) an account and its token; it becomes the active account.
    pub fn remember(&self, vault: &dyn SecretStore, mut acct: SavedAccount, token: &str) -> Result<AccountsFile, String> {
        let key = account_key(&acct.server, &acct.username);
        vault.set(&key, token)?;
        let mut file = self.load();
        acct.server = acct.server.trim_end_matches('/').to_string();
        file.accounts.retain(|a| account_key(&a.server, &a.username) != key);
        file.accounts.insert(0, acct);
        file.active = Some(key);
        self.save(&file)?;
        Ok(file)
    }

    pub fn forget(&self, vault: &dyn SecretStore, key: &str) -> Result<AccountsFile, String> {
        vault.delete(key)?;
        let mut file = self.load();
        file.accounts.retain(|a| account_key(&a.server, &a.username) != key);
        if file.active.as_deref() == Some(key) {
            file.active = None;
        }
        self.save(&file)?;
        Ok(file)
    }

    pub fn activate(&self, vault: &dyn SecretStore, key: &str) -> Result<Option<String>, String> {
        let mut file = self.load();
        if !file.accounts.iter().any(|a| account_key(&a.server, &a.username) == key) {
            return Err("unknown account".into());
        }
        let token = vault.get(key)?;
        file.active = Some(key.to_string());
        self.save(&file)?;
        Ok(token)
    }

    /// Mark the active account as signed out (keeps it in the list for quick re-login).
    pub fn sign_out(&self, vault: &dyn SecretStore, key: &str) -> Result<AccountsFile, String> {
        vault.delete(key)?;
        let mut file = self.load();
        if file.active.as_deref() == Some(key) {
            file.active = None;
        }
        self.save(&file)?;
        Ok(file)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;
    use std::collections::HashMap;

    #[derive(Default)]
    struct MemVault(RefCell<HashMap<String, String>>);
    impl SecretStore for MemVault {
        fn set(&self, k: &str, s: &str) -> Result<(), String> {
            self.0.borrow_mut().insert(k.into(), s.into());
            Ok(())
        }
        fn get(&self, k: &str) -> Result<Option<String>, String> {
            Ok(self.0.borrow().get(k).cloned())
        }
        fn delete(&self, k: &str) -> Result<(), String> {
            self.0.borrow_mut().remove(k);
            Ok(())
        }
    }

    fn acct(server: &str, user: &str) -> SavedAccount {
        SavedAccount { server: server.into(), username: user.into(), display_name: None, avatar_url: None, role: None, last_used: 0.0 }
    }

    #[test]
    fn remember_switch_signout_forget() {
        let dir = std::env::temp_dir().join(format!("moth-acct-{}", std::process::id()));
        let store = AccountsStore { path: dir.join("accounts.json") };
        let vault = MemVault::default();
        store.remember(&vault, acct("https://moth.test/", "Alice"), "tok-a").unwrap();
        let f = store.remember(&vault, acct("https://moth.test", "bob"), "tok-b").unwrap();
        assert_eq!(f.accounts.len(), 2);
        assert_eq!(f.active.as_deref(), Some("https://moth.test|bob"));
        // the file never contains tokens
        let raw = std::fs::read_to_string(&store.path).unwrap();
        assert!(!raw.contains("tok-a") && !raw.contains("tok-b"));
        // switch
        let key_a = account_key("https://moth.test", "alice");
        assert_eq!(store.activate(&vault, &key_a).unwrap().as_deref(), Some("tok-a"));
        assert!(store.activate(&vault, "nope|x").is_err());
        // sign out keeps the account listed but removes its secret
        let f = store.sign_out(&vault, &key_a).unwrap();
        assert_eq!(f.active, None);
        assert_eq!(f.accounts.len(), 2);
        assert_eq!(vault.get(&key_a).unwrap(), None);
        // forget removes it entirely
        let f = store.forget(&vault, &account_key("https://moth.test", "bob")).unwrap();
        assert_eq!(f.accounts.len(), 1);
        std::fs::remove_dir_all(dir).ok();
    }

    #[test]
    fn re_login_replaces_entry_without_duplicates() {
        let dir = std::env::temp_dir().join(format!("moth-acct2-{}", std::process::id()));
        let store = AccountsStore { path: dir.join("accounts.json") };
        let vault = MemVault::default();
        store.remember(&vault, acct("https://s", "Alice"), "1").unwrap();
        let f = store.remember(&vault, acct("https://s", "alice"), "2").unwrap();
        assert_eq!(f.accounts.len(), 1);
        assert_eq!(vault.get(&account_key("https://s", "ALICE")).unwrap().as_deref(), Some("2"));
        std::fs::remove_dir_all(dir).ok();
    }

    #[test]
    fn real_os_vault_roundtrip() {
        let key = format!("moth-test|vault-{}", std::process::id());
        if let Err(e) = OsVault.set(&key, "secret-value") {
            // Windows always has Credential Manager: a failure there is a real bug.
            assert!(!cfg!(windows), "Windows Credential Manager failed: {e}");
            eprintln!("OS credential vault unavailable on this machine, skipping: {e}");
            return;
        }
        assert_eq!(OsVault.get(&key).unwrap().as_deref(), Some("secret-value"));
        OsVault.delete(&key).unwrap();
        assert_eq!(OsVault.get(&key).unwrap(), None);
    }
}
