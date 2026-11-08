/** Readable FastAPI validation failures, shared by local and Cloud requests. */
export function requestError(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => {
      if (!item || typeof item !== "object") return "";
      const field = Array.isArray(item.loc) ? item.loc.filter((p: unknown) => p !== "body" && p !== "query").join(" → ") : "";
      const message = typeof item.msg === "string" ? item.msg : "Invalid request data";
      return field ? `${field}: ${message}` : message;
    }).filter(Boolean);
    if (messages.length) return messages.join("; ");
  }
  return fallback || "The request could not be completed. Please try again.";
}
