/**
 * 1.0 micro-sounds (off by default; Settings → Updates & about → Alerts). Tiny synthesized tones, no audio
 * files: a soft click when sending, a chime when a task or reply finishes, a flourish on a promotion.
 */
import { alertPrefs } from "./alerts";

let ctx: AudioContext | null = null;
function audio(): AudioContext | null {
  if (typeof window === "undefined" || !alertPrefs().sounds) return null;
  try {
    ctx = ctx ?? new (window.AudioContext || (window as any).webkitAudioContext)();
    return ctx;
  } catch { return null; }
}

function tone(freq: number, at: number, dur: number, gain = 0.05, type: OscillatorType = "sine") {
  const a = audio();
  if (!a) return;
  const o = a.createOscillator(), g = a.createGain();
  o.type = type; o.frequency.value = freq;
  const t = a.currentTime + at;
  g.gain.setValueAtTime(0, t);
  g.gain.linearRampToValueAtTime(gain, t + 0.01);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  o.connect(g).connect(a.destination);
  o.start(t); o.stop(t + dur + 0.02);
}

export const sounds = {
  click: () => tone(1800, 0, 0.04, 0.025, "triangle"),
  chime: () => { tone(880, 0, 0.35); tone(1320, 0.09, 0.45, 0.04); },
  flourish: () => [523, 659, 784, 1047].forEach((f, i) => tone(f, i * 0.08, 0.5, 0.045)),
};
