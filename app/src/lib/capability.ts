/** 2.5: what MOTH can really do at its current size, said plainly (it grows as it trains). */
export function honestCapability(params: number | null): string | null {
  if (params == null) return null;
  const m = params / 1e6;
  const size = m >= 1000 ? `${(m / 1000).toFixed(1)} billion` : `${m >= 10 ? Math.round(m) : m.toFixed(1)} million`;
  if (m < 50) return `MOTH is a small model (${size} parameters) that is still learning. It can continue text and short code patterns, but it cannot yet reliably answer questions, write working programs or carry out tasks on your PC. It improves as it trains.`;
  if (m < 1000) return `MOTH (${size} parameters) can complete and explain short code, but longer programs and multi-step tasks often need checking. Review what it changes.`;
  return `MOTH has ${size} parameters. Review what it changes before you rely on it.`;
}
