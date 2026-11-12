/**
 * Parameter counts as MOTH Cloud reports them. `params_verified` is true when the server counted the
 * number from the release's saved weight tensors (0.6.3); otherwise it is the count the package
 * declared at registration, shown as not yet verified rather than as "actual".
 */
export function paramsLabel(params: number | null | undefined, verified?: boolean | null): string {
  if (params == null) return "Parameters not recorded";
  const n = `${params.toLocaleString()} parameters`;
  if (verified === true) return `${n} · counted from the saved weights`;
  if (verified === false) return `${n} · registered count, not yet counted from the weights`;
  return n;
}
