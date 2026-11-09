export function friendlyError(detail: string): string {
  if (/inference endpoint unavailable|failed to fetch|networkerror|connection refused/i.test(detail)) return "MOTH can’t connect to the AI service. Check your connection and try again.";
  if (/tokenizer incompatib|tokenizer.*mismatch/i.test(detail)) return "This dataset uses a different tokenizer. Select a compatible dataset or prepare it with the model’s tokenizer.";
  if (/candidate promotion rejected/i.test(detail)) return "The new model didn’t pass the required checks. Your current model is still in use.";
  if (/no training tokens|no text records were extracted/i.test(detail)) return "No usable training text was found. Check the selected files and their format.";
  return detail;
}
export function ErrorNotice({ error }: { error: string | null | undefined }) {
  if (!error) return null;
  const plain = friendlyError(error);
  return <div role="alert" className="rounded-lg border border-danger/30 bg-danger/5 p-3 text-xs text-danger">
    <p>{plain}</p>{plain !== error && <details className="mt-2 text-muted"><summary className="cursor-pointer">Technical details</summary><pre className="mt-2 max-h-40 whitespace-pre-wrap break-words">{error}</pre></details>}
  </div>;
}
