import { isTauri } from "./backend";

/** Open an https URL (checkout, billing portal) in the user's default browser. */
export async function openExternal(url: string) {
  if (!/^https?:\/\//i.test(url)) throw new Error("refusing to open a non-web URL");
  if (isTauri()) {
    const { openUrl } = await import("@tauri-apps/plugin-opener");
    await openUrl(url);
    return;
  }
  window.open(url, "_blank", "noopener");
}
