import { useEffect, useRef, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import { Square, X } from "lucide-react";
import { del, post } from "@/lib/backend";
import { subscribe } from "@/lib/events";
import { appStore, useApp } from "@/lib/app-state";
import { Button } from "@/components/ui/button";

/**
 * Line-oriented terminal: commands run in the backend (streamed output,
 * persistent cwd, Ctrl+C cancels the process tree). Not a full PTY in v0.1.
 */
export function TerminalPanel() {
  const project = useApp((s) => s.project);
  const host = useRef<HTMLDivElement>(null);
  const [running, setRunning] = useState(false);
  const sessionRef = useRef<string | null>(null);
  const termRef = useRef<Terminal | null>(null);

  useEffect(() => {
    if (!host.current) return;
    const term = new Terminal({
      fontFamily: "'Cascadia Mono', Consolas, monospace",
      fontSize: 12.5,
      cursorBlink: true,
      convertEol: true,
      theme: {
        background: "#0b0b0b", foreground: "#e6e6e6", cursor: "#ff3b47", selectionBackground: "#C1121F66",
        red: "#ff4d5a", brightRed: "#ff6b75", green: "#3fb27f", yellow: "#e0a63a", blue: "#7aa2f7",
      },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(host.current);
    fit.fit();
    termRef.current = term;
    const ro = new ResizeObserver(() => {
      try { fit.fit(); } catch { /* hidden */ }
    });
    ro.observe(host.current);

    let line = "";
    let cwd = "";
    let busy = false;
    const history: string[] = [];
    let hIndex = -1;
    const prompt = () => term.write(`\r\n\x1b[38;2;193;18;31m❯\x1b[0m \x1b[90m${cwd}\x1b[0m\r\n$ `);

    const unsub = subscribe("terminal", (e) => {
      if (e.session !== sessionRef.current) return;
      if (e.kind === "output") term.write(e.data);
      if (e.kind === "exit") {
        busy = false;
        setRunning(false);
        cwd = e.cwd ?? cwd;
        if (e.cancelled) term.write("\r\n\x1b[33m^C cancelled\x1b[0m");
        else if (e.timed_out) term.write("\r\n\x1b[33mtimed out\x1b[0m");
        else if (e.code !== 0 && e.code !== null) term.write(`\r\n\x1b[31mexit ${e.code}\x1b[0m`);
        prompt();
      }
    });

    let disposed = false;
    post<{ id: string; cwd: string }>("/api/terminals", { project_id: project?.id ?? null }).then((s) => {
      if (disposed) {
        del(`/api/terminals/${s.id}`);
        return;
      }
      sessionRef.current = s.id;
      cwd = s.cwd;
      term.write("\x1b[38;2;193;18;31mMOTH\x1b[0m terminal — commands run in your workspace. Ctrl+C cancels.");
      prompt();
    });

    const data = term.onData((d) => {
      const sid = sessionRef.current;
      if (!sid) return;
      if (d === "\x03") {
        if (busy) post(`/api/terminals/${sid}/cancel`);
        else { line = ""; term.write("^C"); prompt(); }
        return;
      }
      if (busy) return;
      if (d === "\r") {
        const cmd = line.trim();
        line = "";
        hIndex = -1;
        term.write("\r\n");
        if (!cmd) return prompt();
        if (cmd === "clear" || cmd === "cls") { term.clear(); return prompt(); }
        history.unshift(cmd);
        busy = true;
        setRunning(true);
        post(`/api/terminals/${sid}/run`, { command: cmd }).catch((err) => {
          busy = false;
          setRunning(false);
          term.write(`\x1b[31m${String(err)}\x1b[0m`);
          prompt();
        });
      } else if (d === "\x7f" || d === "\b") {
        if (line.length) { line = line.slice(0, -1); term.write("\b \b"); }
      } else if (d === "\x1b[A" || d === "\x1b[B") {
        hIndex = d === "\x1b[A" ? Math.min(history.length - 1, hIndex + 1) : Math.max(-1, hIndex - 1);
        const next = hIndex >= 0 ? history[hIndex] : "";
        term.write("\b \b".repeat(line.length) + next);
        line = next;
      } else if (d.startsWith("\x1b")) {
        /* ignore other escape sequences */
      } else {
        const printable = d.replace(/[\x00-\x1f]/g, "");
        line += printable;
        term.write(printable);
      }
    });

    return () => {
      disposed = true;
      unsub();
      data.dispose();
      ro.disconnect();
      term.dispose();
      if (sessionRef.current) del(`/api/terminals/${sessionRef.current}`).catch(() => {});
      sessionRef.current = null;
    };
  }, [project?.id]);

  return (
    <div className="flex h-full flex-col bg-[#0b0b0b]">
      <div className="flex h-8 shrink-0 items-center justify-between border-b border-border px-3">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">Terminal</span>
        <div className="flex items-center gap-1">
          {running && (
            <Button variant="ghost" size="sm" onClick={() => sessionRef.current && post(`/api/terminals/${sessionRef.current}/cancel`)}>
              <Square className="text-accent" /> Stop
            </Button>
          )}
          <Button variant="ghost" size="icon-sm" onClick={() => appStore.setState({ terminalOpen: false })}>
            <X />
          </Button>
        </div>
      </div>
      <div ref={host} className="min-h-0 flex-1" onClick={() => termRef.current?.focus()} />
    </div>
  );
}
