/**
 * Which MOTH Cloud this copy of MOTH Code talks to.
 *
 * Release builds can carry a built-in default address (``VITE_MOTH_CLOUD_URL``, from the repository
 * variable ``MOTH_CLOUD_URL``). The user can always choose another one in Settings → Connection —
 * e.g. while the permanent domain's HTTPS isn't ready — without rebuilding the app; "Use default"
 * returns to the built-in address. The choice is stored under the same key v0.2 used, so an address
 * entered in v0.2 keeps working after updating.
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

const SERVER_KEY = "moth.serverUrl"; // the user's chosen MOTH Cloud address (also used by v0.2)
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
export const userServer = (): string | null => read(SERVER_KEY);
export const setUserServer = (url: string | null) => write(SERVER_KEY, url);
export const developerMode = (): boolean => MOTH_ENV !== "production" || read(DEV_MODE_KEY) === "1";
export const setDeveloperMode = (on: boolean) => write(DEV_MODE_KEY, on ? "1" : null);

/** The address in use: the user's choice, else the built-in default. */
export function resolveServer(): string {
  return userServer() || officialServer() || "";
}

/** True when this build has a built-in default address. */
export const hasOfficialServer = (): boolean => !!officialServer();
