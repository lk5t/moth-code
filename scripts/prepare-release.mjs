// Prepares app/src-tauri/tauri.release.conf.json for a release build.
// - Verifies the git tag (if any) matches the app/package/backend versions.
// - Injects the updater public key from TAURI_UPDATER_PUBKEY.
// - Disables updater artifacts (with a warning) when signing is not configured,
//   so unsigned builds are never presented as updatable.
import { readFileSync, writeFileSync } from "node:fs";

const root = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const read = (p) => readFileSync(root + p, "utf8");
const conf = JSON.parse(read("app/src-tauri/tauri.conf.json"));
const pkg = JSON.parse(read("app/package.json"));
const cargo = read("app/src-tauri/Cargo.toml").match(/^version = "(.+)"/m)[1];
const py = read("backend/pyproject.toml").match(/^version = "(.+)"/m)[1];
const init = read("backend/moth/__init__.py").match(/__version__ = "(.+)"/)[1];
const versions = { "tauri.conf.json": conf.version, "package.json": pkg.version, "Cargo.toml": cargo, "pyproject.toml": py, "moth/__init__.py": init };
const unique = new Set(Object.values(versions));
if (unique.size !== 1) {
  console.error("Version mismatch:", versions);
  process.exit(1);
}
const version = conf.version;
const ref = process.env.RELEASE_TAG || process.env.GITHUB_REF_NAME || "";
if (ref.startsWith("v") && ref.slice(1) !== version) {
  console.error(`Tag ${ref} does not match app version ${version}`);
  process.exit(1);
}

const releasePath = "app/src-tauri/tauri.release.conf.json";
const release = JSON.parse(read(releasePath));
const pubkey = (process.env.TAURI_UPDATER_PUBKEY || "").trim();
const hasKey = process.env.HAS_SIGNING_KEY === "true";
if (pubkey && hasKey) {
  release.plugins = { updater: { pubkey } };
  release.bundle.createUpdaterArtifacts = true;
  console.log("Signed updates: enabled");
} else {
  release.bundle.createUpdaterArtifacts = false;
  console.warn("::warning::Updater signing is not configured (TAURI_UPDATER_PUBKEY variable and TAURI_SIGNING_PRIVATE_KEY secret). " +
    "This build will not offer in-app updates. See docs/RELEASING.md.");
}
writeFileSync(root + releasePath, JSON.stringify(release, null, 2) + "\n");
console.log(`Prepared release config for MOTH Code ${version}`);
