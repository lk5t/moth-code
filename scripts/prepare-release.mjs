// Prepares a MOTH Code release build.
// - Verifies every component (desktop, backend, server, worker) has the same version, matching the tag.
// - Builds the official MOTH Cloud endpoint into the app (MOTH_CLOUD_URL, a repository variable) so
//   users never configure a server; staging builds use MOTH_STAGING_URL.
// - Points the Tauri updater at MOTH Cloud's update service and injects the updater public key.
// - Disables updater artifacts (with a warning) when signing or the endpoint is missing, so unsigned
//   builds are never presented as updatable.
import { readFileSync, writeFileSync } from "node:fs";

const root = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const read = (p) => readFileSync(root + p, "utf8");
const conf = JSON.parse(read("app/src-tauri/tauri.conf.json"));
const pkg = JSON.parse(read("app/package.json"));
const pyv = (p, re) => read(p).match(re)[1];
const versions = {
  "tauri.conf.json": conf.version,
  "package.json": pkg.version,
  "Cargo.toml": pyv("app/src-tauri/Cargo.toml", /^version = "(.+)"/m),
  "backend": pyv("backend/moth/__init__.py", /__version__ = "(.+)"/),
  "server": pyv("server/moth_server/__init__.py", /__version__ = "(.+)"/),
  "worker": pyv("worker/moth_worker/__init__.py", /__version__ = "(.+)"/),
};
if (new Set(Object.values(versions)).size !== 1) {
  console.error("Version mismatch:", versions);
  process.exit(1);
}
const version = conf.version;
const ref = process.env.RELEASE_TAG || process.env.GITHUB_REF_NAME || "";
if (ref.startsWith("v") && ref.slice(1) !== version) {
  console.error(`Tag ${ref} does not match version ${version}`);
  process.exit(1);
}

const channel = process.env.RELEASE_CHANNEL || "stable";
const env = channel === "stable" ? "production" : "staging";
const cloud = ((env === "production" ? process.env.MOTH_CLOUD_URL : process.env.MOTH_STAGING_URL || process.env.MOTH_CLOUD_URL) || "")
  .trim().replace(/\/+$/, "");
if (cloud && !cloud.startsWith("https://")) {
  console.error(`MOTH Cloud URL must be https:// (got ${cloud})`);
  process.exit(1);
}
const lines = [`VITE_MOTH_ENV=${env}`];
if (cloud) lines.push(env === "production" ? `VITE_MOTH_CLOUD_URL=${cloud}` : `VITE_MOTH_STAGING_URL=${cloud}`);
writeFileSync(root + "app/.env.production.local", lines.join("\n") + "\n");
if (cloud) console.log(`Official MOTH Cloud endpoint: ${cloud} (${env})`);
else console.warn("::warning::MOTH_CLOUD_URL is not set: this build has no built-in MOTH Cloud address and no automatic updates.");

const releasePath = "app/src-tauri/tauri.release.conf.json";
const release = JSON.parse(read(releasePath));
// The updater public key is committed (app/src-tauri/updater.pub); a repository variable can override it.
let pubkey = (process.env.TAURI_UPDATER_PUBKEY || "").trim();
try {
  if (!pubkey) pubkey = read("app/src-tauri/updater.pub").trim();
} catch {
  /* no committed key */
}
const hasKey = process.env.HAS_SIGNING_KEY === "true";
if (pubkey && hasKey && cloud) {
  release.plugins = { updater: { pubkey, endpoints: [`${cloud}/v1/updates/desktop/{{target}}/{{arch}}/{{current_version}}?channel=${channel}`],
                                 windows: { installMode: "passive" } } };
  release.bundle.createUpdaterArtifacts = true;
  console.log("Signed automatic updates: enabled");
} else {
  delete release.plugins;
  release.bundle.createUpdaterArtifacts = false;
  console.warn("::warning::Automatic updates are disabled for this build (needs MOTH_CLOUD_URL, TAURI_UPDATER_PUBKEY and the " +
    "TAURI_SIGNING_PRIVATE_KEY secret). See docs/RELEASING.md.");
}
writeFileSync(root + releasePath, JSON.stringify(release, null, 2) + "\n");
console.log(`Prepared release configuration for MOTH ${version} (${channel})`);
