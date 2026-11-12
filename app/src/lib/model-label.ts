/** The public name of a native model: "MOTH 0.0.x" (0.7.0). Internal package/registry names such as
 * "moth-evolution-v50-e8" are storage identifiers and are never shown as the model's name. */
export function modelLabel(model?: { name?: string; display_name?: string; model_version?: string | number } | string | null): string {
  const raw = typeof model === "string" ? model : model?.display_name ||
    (typeof model?.model_version === "string" ? `MOTH ${model.model_version}` : model?.name) || "MOTH";
  if (raw.toLowerCase() === "moth-200k-v0.1-step500") return "MOTH 0.0.1";
  return /^moth-(evolution|network|cloud|base|test)[-\w.]*$/i.test(raw) ? "MOTH" : raw;
}
