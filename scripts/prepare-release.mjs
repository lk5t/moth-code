// Prepares a MOTH Code desktop build (app/src-tauri/tauri.release.conf.json + app/.env.production.local).
//
// - Verifies the desktop version (tauri.conf.json, package.json, Cargo.toml and the bundled backend)
//   is consistent and matches the tag (vX.Y.Z or desktop-vX.Y.Z).
// - Optionally builds in a default MOTH Cloud address (MOTH_CLOUD_URL, a repository variable). Users can
//   change the address in Settings → Connection; nothing temporary is ever built in.
// - Enables signed automatic updates when the updater key is available. The update endpoint is chosen
//   at runtime from the connected MOTH Cloud address, so it is not part of the build.
//   requireSignedVersion rejects an update whose signed version differs from the offered one.
// - MOTH_UPDATE_TEST_BUILD=1 (CI update test only): allows a loopback http:// server.
//   CI closes the real window to install a downloaded update. Never set for releases.
import { readFileSync, writeFileSync } from "node:fs";

const root = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const read = (p) => readFileSync(root + p, "utf8");
const conf = JSON.parse(read("app/src-tauri/tauri.conf.json"));
const pkg = JSON.parse(read("app/package.json"));
const grab = (p, re) => read(p).match(re)[1];
const versions = {
  "tauri.conf.json": conf.version,
  "package.json": pkg.version,
  "Cargo.toml": grab("app/src-tauri/Cargo.toml", /^version = "(.+)"/m),
  "backend (bundled)": grab("backend/moth/__init__.py", /__version__ = "(.+)"/),
};
if (new Set(Object.values(versions)).size !== 1) {
  console.error("Version mismatch:", versions);
  process.exit(1);
}
const version = conf.version;
const test = process.env.MOTH_UPDATE_TEST_BUILD === "1";
const ref = process.env.RELEASE_TAG || "";
const tagVersion = ref.replace(/^desktop-/, "").replace(/^v/, "");
if (ref && !test && tagVersion !== version) {
  console.error(`Tag ${ref} does not match version ${version}`);
  process.exit(1);
}

const channel = process.env.RELEASE_CHANNEL || "stable";
const env = channel === "stable" ? "production" : "staging";
const cloud = (process.env.MOTH_CLOUD_URL || "").trim().replace(/\/+$/, "");
if (cloud && !cloud.startsWith("https://") && !test) {
  console.error(`The built-in MOTH Cloud address must use https:// (got ${cloud})`);
  process.exit(1);
}
const lines = [`VITE_MOTH_ENV=${env}`];
if (cloud) lines.push(env === "production" ? `VITE_MOTH_CLOUD_URL=${cloud}` : `VITE_MOTH_STAGING_URL=${cloud}`);
if (test) lines.push("VITE_MOTH_UPDATE_TEST=1");
writeFileSync(root + "app/.env.production.local", lines.join("\n") + "\n");
console.log(cloud ? `Built-in MOTH Cloud address: ${cloud} (users can change it in Settings → Connection)` :
  "No built-in MOTH Cloud address: the app asks for one on first sign-in (Settings → Connection).");

const releasePath = "app/src-tauri/tauri.release.conf.json";
const release = JSON.parse(read(releasePath));
let pubkey = (process.env.TAURI_UPDATER_PUBKEY || "").trim();
try {
  if (!pubkey) pubkey = read("app/src-tauri/updater.pub").trim();
} catch {
  /* no committed key */
}
const hasKey = process.env.HAS_SIGNING_KEY === "true";
if (pubkey && hasKey) {
  release.plugins = {
    updater: {
      pubkey, endpoints: [], requireSignedVersion: true, windows: { installMode: "passive" },
      ...(test ? { dangerousInsecureTransportProtocol: true } : {}),
    },
  };
  release.bundle.createUpdaterArtifacts = true;
  console.log(`Signed automatic updates: enabled${test ? " (TEST BUILD: loopback http allowed)" : ""}`);
} else {
  delete release.plugins;
  release.bundle.createUpdaterArtifacts = false;
  console.warn("::warning::Automatic updates are disabled for this build (needs the TAURI_SIGNING_PRIVATE_KEY secret). " +
    "See docs/RELEASING.md.");
}
if (process.env.MOTH_SKIP_BACKEND_BUNDLE === "1") release.bundle.resources = {}; // update test builds only
writeFileSync(root + releasePath, JSON.stringify(release, null, 2) + "\n");
console.log(`Prepared MOTH Code ${version} (${channel})`);
