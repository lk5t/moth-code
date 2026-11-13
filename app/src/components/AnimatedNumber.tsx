/**
 * 0.9.1: a number that counts smoothly to its new value (and glows briefly when it changes).
 * Reduced-motion users get the new value at once.
 */
import { useEffect, useRef, useState } from "react";

const reduced = () => typeof window === "undefined" || !window.matchMedia || window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function AnimatedNumber({ value, digits = 0, duration = 600, className }:
  { value: number; digits?: number; duration?: number; className?: string }) {
  const [shown, setShown] = useState(value);
  const [flash, setFlash] = useState(false);
  const from = useRef(value);
  useEffect(() => {
    if (value === from.current) return;
    const start = from.current, t0 = performance.now();
    from.current = value;
    setFlash(true);
    const off = setTimeout(() => setFlash(false), 900);
    if (reduced() || !Number.isFinite(start)) { setShown(value); return () => clearTimeout(off); }
    let raf = 0;
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / duration);
      const e = 1 - Math.pow(1 - k, 3); // ease-out cubic
      setShown(start + (value - start) * e);
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => { cancelAnimationFrame(raf); clearTimeout(off); };
  }, [value, duration]);
  return <span className={`${className ?? ""}${flash ? " value-changed" : ""}`}>
    {shown.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 })}
  </span>;
}
