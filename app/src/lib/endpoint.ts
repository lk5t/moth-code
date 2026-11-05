/**
 * Which MOTH Cloud this copy of MOTH Code talks to.
 *
 * Production builds have the official HTTPS endpoint built in (``VITE_MOTH_CLOUD_URL``, set by the
 * release workflow from the repository variable ``MOTH_CLOUD_URL``), so users never type a server
 * address. Staging and development builds use their own endpoints. A developer override exists for
 * testing only (Settings → Advanced, developer mode) and is never shown in normal onboarding.
 */
export type MothEnv = "production" | "staging" | "development";

const env = import.meta.env;
export const APP_VERSION: string = (env.VITE_APP_VERSION as string | undefined) ?? "0.0.0";
export const MOTH_ENV: MothEnv = ((env.VITE_MOTH_ENV as MothEnv | undefined) ?? (env.DEV ? "development" : "production"));
export const CLIENT_HEADER = `desktop/${APP_VERSION}`;

const OFFICIAL: Record<MothEnv, string> = {
  production: (env.VITE_MOTH_CLOUD_URL as string | undefined) ?? "",
  staging: (env.VITE_MOTH_STAGING_URL as string | undefined) ?? "",
  development: (env.VITE_MOTH_DEV_URL as string | undefined) ?? "http://127.0.0.1:8900",
};

const OVERRIDE_KEY = "moth.dev.serverOverride";
const LEGACY_KEY = "moth.serverUrl"; // v0.2 stored a typed-in server address here
const DEV_MODE_KEY = "moth.dev.mode";

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null) {
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    /* storage unavailable */
  }
}

export const officialServer = (): string => OFFICIAL[MOTH_ENV].replace(/\/+$/, "");
export const developerOverride = (): string | null => read(OVERRIDE_KEY);
export const setDeveloperOverride = (url: string | null) => write(OVERRIDE_KEY, url);
export const developerMode = (): boolean => MOTH_ENV !== "production" || read(DEV_MODE_KEY) === "1";
export const setDeveloperMode = (on: boolean) => write(DEV_MODE_KEY, on ? "1" : null);

/** The server to use: a developer override, else the official endpoint, else (builds without one,
 *  e.g. v0.2 upgrades of a self-hosted setup) the address the user entered before. */
export function resolveServer(): string {
  return developerOverride() || officialServer() || read(LEGACY_KEY) || "";
}

/** True when the user never needs to see or type a server address. */
export const hasOfficialServer = (): boolean => !!officialServer();

export function rememberLegacyServer(url: string) {
  write(LEGACY_KEY, url);
}
