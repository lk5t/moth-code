import { cn } from "@/lib/utils";
import { useEffect, useId, useRef, useState } from "react";

/** The MOTH emblem (source of truth: branding/moth-emblem.svg). */
export function MothEmblem({ className, glow = false, motion = "none" }: {
  className?: string; glow?: boolean; motion?: "none" | "idle" | "working" | "thinking" | "generating" | "training" | "evaluating" | "deploying" | "error" | "offline";
}) {
  const ref = useRef<SVGSVGElement>(null);
  const [onScreen, setOnScreen] = useState(true);
  const [pageVisible, setPageVisible] = useState(() => !document.hidden);
  useEffect(() => {
    const changed = () => setPageVisible(!document.hidden);
    document.addEventListener("visibilitychange", changed);
    const observer = typeof IntersectionObserver !== "undefined" ? new IntersectionObserver(([entry]) => setOnScreen(entry.isIntersecting)) : null;
    if(ref.current) observer?.observe(ref.current);
    return () => {observer?.disconnect();document.removeEventListener("visibilitychange", changed);};
  }, []);
  const id = `moth-${useId().replace(/:/g, "")}`;
  return (
    <svg ref={ref} viewBox="0 0 512 512" data-motion={motion} data-visible={onScreen && pageVisible}
      className={cn("moth-emblem", `moth-motion-${motion}`, glow && "animate-pulse-glow", className)} aria-hidden>
      <defs>
        <linearGradient id={`${id}-mw`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#E23A44" />
          <stop offset="0.55" stopColor="#C1121F" />
          <stop offset="1" stopColor="#5A0810" />
        </linearGradient>
        <linearGradient id={`${id}-mh`} x1="0" y1="0" x2="0.6" y2="1">
          <stop offset="0" stopColor="#9E0E18" />
          <stop offset="1" stopColor="#2A0407" />
        </linearGradient>
        <linearGradient id={`${id}-mb`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#2C2C2C" />
          <stop offset="1" stopColor="#0B0B0B" />
        </linearGradient>
        <g id={`${id}-half`}>
          <path d="M244 196 L140 146 L30 162 L74 238 L234 258 Z" fill={`url(#${id}-mw)`} />
          <path d="M238 266 L112 284 L138 346 L208 378 L244 304 Z" fill={`url(#${id}-mh)`} />
          <g stroke="#080808" strokeWidth="4.5" fill="none" strokeLinecap="square" strokeLinejoin="miter">
            <path d="M232 210 L150 176 L82 176" />
            <path d="M230 230 L168 222 L146 204 L108 206" />
            <path d="M230 248 L124 234" />
            <path d="M232 282 L172 296 L146 318" />
            <path d="M236 296 L210 340 L196 356" />
          </g>
          <g fill="#080808">
            <circle cx="82" cy="176" r="6.5" />
            <circle cx="108" cy="206" r="6.5" />
            <circle cx="146" cy="318" r="6.5" />
            <circle cx="196" cy="356" r="5.5" />
          </g>
          <g stroke="#C1121F" strokeWidth="3" fill="none" strokeLinecap="round">
            <path d="M250 176 L226 132 L204 108" strokeWidth="3.5" />
            <path d="M240 158 L230 162 M234 146 L224 150 M228 134 L218 138 M218 122 L209 125" />
            <path d="M240 158 L244 148 M234 146 L238 136 M228 134 L232 124 M218 122 L220 113" />
          </g>
        </g>
      </defs>
      <g className="moth-wing moth-wing-left"><use href={`#${id}-half`} /></g>
      <g className="moth-wing moth-wing-right"><use href={`#${id}-half`} transform="translate(512 0) scale(-1 1)" /></g>
      <path
        d="M256 168 L268 182 L270 210 L276 240 L268 330 L256 372 L244 330 L236 240 L242 210 L244 182 Z"
        fill={`url(#${id}-mb)`}
        stroke="#C1121F"
        strokeWidth="3"
        strokeLinejoin="round"
      />
      <path d="M246 262 L266 262 M246 286 L266 286 M248 310 L264 310" stroke="#C1121F" strokeWidth="2" opacity="0.55" />
      <circle cx="256" cy="218" r="5" fill="#E23A44" />
    </svg>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("font-semibold tracking-[0.32em] text-fg", className)}>
      MOTH<span className="ml-2 font-light tracking-[0.2em] text-muted">CODE</span>
    </span>
  );
}
