/** Product label for the existing legacy checkpoint; registry IDs and weights stay intact. */
export function modelLabel(model?: { name?: string; display_name?: string; model_version?: string | number } | string | null): string {
  const name = typeof model === "string" ? model : model?.display_name ||
    (typeof model?.model_version === "string" ? `MOTH ${model.model_version}` : model?.name) || "MOTH";
  return name.toLowerCase() === "moth-200k-v0.1-step500" ? "MOTH 0.0.1" : name;
}
