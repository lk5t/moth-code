/**
 * 1.0 home screen: a greeting, what MOTH is doing right now, today's progress, recent projects and chats,
 * and a live activity feed. Everything shown is measured; nothing is decorative guesswork.
 */
import { useEffect, useState } from "react";
import { Brain, CalendarDays, Cpu, FolderGit2, FolderOpen, GitBranch, MessageSquare, Plus, Sparkles, Zap } from "lucide-react";
import { serverApi, useAccount } from "@/lib/account";
import { get, put } from "@/lib/backend";
import { useCloudProgress } from "@/lib/cloud-progress";
import { useApp, appStore } from "@/lib/app-state";
import { navigate } from "@/lib/navigation";
import { useResource } from "@/lib/hooks";
import { modelLabel } from "@/lib/model-label";
import { timeAgo } from "@/lib/utils";
import { LivingMoth } from "@/components/LivingMoth";
import { AnimatedNumber } from "@/components/AnimatedNumber";
import { Button } from "@/components/ui/button";
import { requestChat } from "@/components/SidebarCollections";
import { pickProject, openProjectPath } from "@/features/workspace/project-actions";
import { StageMeter } from "@/features/intelligence/live/Learning";
import { CloneGitHub } from "./CloneGitHub";
import { SideBySide } from "@/features/intelligence/SideBySide";
import { BenchmarkTrend, Leaderboard } from "./HomeExtras";

type Any = Record<string, any>;

export function greeting(hour: number): string {
  return hour < 5 ? "Good night" : hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
}

function Tile({ icon, label, value, live }: { icon: React.ReactNode; label: string; value: number | string | null; live?: boolean }) {
  return <div className="lift relative overflow-hidden rounded-xl border border-border bg-surface px-3 py-2.5">
    {live && <span className="pointer-events-none absolute -right-5 -top-5 size-16 rounded-full bg-accent/20 blur-xl" />}
    <div className="flex items-center gap-1.5 text-[0.65625rem] uppercase tracking-wider text-faint [&_svg]:size-3.5 [&_svg]:text-accent">{icon}{label}{live && <span className="live-dot ml-auto" />}</div>
    <div className="mt-1 font-mono text-lg text-fg">{typeof value === "number" ? <AnimatedNumber value={value} /> : value ?? "—"}</div>
  </div>;
}

export function HomeView() {
  const user = useAccount((s) => s.user);
  const { data: p } = useCloudProgress();
  const projects = useApp((s) => s.projects);
  const { data: chats } = useResource<{ id: number; title: string; updated_at?: number }[]>("/api/conversations?scope=general", [], []);
  const { data: activity } = useResource<{ id: number; ts: number; kind: string; message: string }[]>("/api/activity", ["files", "activity"], []);
  const [now, setNow] = useState(() => new Date());
  const [cloning, setCloning] = useState(false);
  useEffect(() => { const t = setInterval(() => setNow(new Date()), 60_000); return () => clearInterval(t); }, []);

  const training = p?.training;
  const running = (training?.experiments ?? []).find((e: Any) => e.status === "running");
  const m = running?.measurement ?? {};
  const name = user?.username ? `, ${user.username}` : "";
  const status = !p ? "Connecting to MOTH Cloud…" : running ? (running.successor ? "Training its bigger successor" : "Learning right now")
    : training?.paused ? "Paused" : training?.enabled ? "Planning what to learn next" : "Resting";
  return <div className="h-full overflow-auto">
    <div className="mx-auto flex max-w-6xl flex-col gap-4 p-3 sm:p-5">
      <header className="ambient-hero relative overflow-hidden rounded-2xl border border-border p-5">
        <div className="relative flex flex-wrap items-center gap-4">
          <LivingMoth className="size-16 shrink-0" />
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-semibold tracking-tight">{greeting(now.getHours())}{name}</h1>
            <p className="mt-1 flex items-center gap-2 text-sm text-muted">{running && <span className="live-dot" />}
              {p?.current ? modelLabel(p.current) : "MOTH"} · {status}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => requestChat(null)}><Plus /> New chat</Button>
            <Button variant="secondary" onClick={() => void pickProject()}><FolderOpen /> Open project</Button>
            <Button variant="secondary" aria-expanded={cloning} onClick={() => setCloning((v) => !v)}><GitBranch /> Clone from GitHub</Button>
          </div>
        </div>
      </header>

      {cloning && <CloneGitHub onClose={() => setCloning(false)} />}

      <section aria-label="Today" className="stagger grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile icon={<Zap />} label="Tokens learned (this run)" value={typeof m.tokens_seen === "number" ? m.tokens_seen : null} live={!!running} />
        <Tile icon={<Brain />} label="Parameters" value={typeof p?.current?.params === "number" ? p.current.params : null} />
        <Tile icon={<Sparkles />} label="Workers online" value={typeof p?.network?.workers_online === "number" ? p.network.workers_online : null} live={(p?.network?.workers_online ?? 0) > 0} />
        <Tile icon={<MessageSquare />} label="Your chats" value={chats?.length ?? null} />
      </section>

      <Honest params={typeof p?.current?.params === "number" ? p.current.params : null} />

      {/* 2.1: everyone sees MOTH learning; the Owner can open the full live view */}
      {running && <section aria-label="MOTH is learning" className="grid gap-3 animate-slide-up md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <StageMeter loss={m.val_loss ?? m.train_loss} per={running.loss_per === "token" ? "token" : "byte"} />
        <button disabled={user?.role !== "owner"} onClick={() => navigate("intelligence")} className="lift rounded-lg border border-border bg-bg p-3 text-left text-xs disabled:cursor-default">
          <span className="flex items-center gap-1.5 text-faint"><span className="live-dot" />MOTH is learning</span>
          <span className="mt-1 block text-sm text-fg">{typeof m.fraction === "number" ? `${Math.round(m.fraction * 100)}% of this training run` : "Starting…"}</span>
          <span className="mt-1 block text-muted">{running.successor ? "Training a bigger, smarter MOTH. It takes over only if it passes every check." : "Each run that passes every check makes MOTH a little smarter."}</span>
          {user?.role === "owner" && <span className="mt-1 block text-accent">Watch it learn →</span>}
        </button>
      </section>}

      <WeekAndExamples />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]"><BenchmarkTrend /><Leaderboard /></div>

      <div className="grid gap-4 lg:grid-cols-3">
        <section aria-label="Recent projects" className="rounded-xl border border-border bg-surface p-3">
          <h2 className="mb-2 flex items-center gap-1.5 text-xs font-medium"><FolderGit2 className="size-3.5 text-accent" /> Recent projects</h2>
          {projects.length ? <ul className="stagger space-y-1">{[...projects].sort((a, b) => (b.last_opened ?? 0) - (a.last_opened ?? 0)).slice(0, 6).map((pr) =>
            <li key={pr.id}><button className="lift flex w-full items-center gap-2 rounded-md border border-transparent px-2 py-1.5 text-left text-xs hover:border-border"
              onClick={() => void openProjectPath(pr.path).then(() => { appStore.setState({ view: "workspace" }); })}>
              <span className="min-w-0 flex-1 truncate">{pr.name}</span><span className="text-faint">{pr.last_opened ? timeAgo(pr.last_opened) : ""}</span></button></li>)}</ul>
            : <Friendly text="No projects yet. Open a folder and MOTH can read, change and test its code with you." />}
        </section>
        <section aria-label="Recent chats" className="rounded-xl border border-border bg-surface p-3">
          <h2 className="mb-2 flex items-center gap-1.5 text-xs font-medium"><MessageSquare className="size-3.5 text-accent" /> Recent chats</h2>
          {chats?.length ? <ul className="stagger space-y-1">{chats.slice(0, 6).map((c) => <li key={c.id}>
            <button className="lift w-full truncate rounded-md border border-transparent px-2 py-1.5 text-left text-xs hover:border-border" onClick={() => requestChat(c.id, c.title)}>{c.title}</button></li>)}</ul>
            : <Friendly text="Nothing here yet. Say hello — MOTH is still young, so be patient with it." />}
        </section>
        <section aria-label="Activity" className="rounded-xl border border-border bg-surface p-3">
          <h2 className="mb-2 flex items-center gap-1.5 text-xs font-medium"><span className="live-dot" /> Activity</h2>
          {activity?.length ? <ol className="stagger max-h-64 space-y-1.5 overflow-auto">{collapseRepeats(activity).slice(0, 12).map((a) =>
            <li key={a.id} className="animate-message-in text-xs"><span className="text-fg">{a.message}</span>{a.times > 1 && <span className="text-faint"> ×{a.times}</span>} <span className="text-faint">· {timeAgo(a.ts)}</span></li>)}</ol>
            : <Friendly text="Quiet for now. Tasks, file changes and MOTH's news appear here as they happen." />}
        </section>
      </div>
    </div>
  </div>;
}

const fromCloud = (url: string) => serverApi<Any>(url);
const short = (n: number) => n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}K` : String(n);

/** 2.3.1: this week in plain numbers, MOTH's own answers (before and after its last promotion) and one click
 * to let this PC help train. */
function WeekAndExamples() {
  const server = useAccount((s) => s.serverUrl), token = useAccount((s) => s.token);
  const { data: w } = useResource<Any>(token ? "/v1/intelligence/summary" : null, [], undefined, server + "\0" + token, fromCloud);
  const { data: pc, reload: reloadPc } = useResource<Any>("/api/participant", [], undefined, "", get);
  const [joined, setJoined] = useState<string | null>(null);
  if (!w) return null;
  const promoted: Any[] = w.promoted ?? [], ex: Any = w.experiments ?? {};
  const tried = Object.values(ex).reduce((a: number, b) => a + (b as number), 0);
  const grown = w.params_at_start && w.current?.params && w.current.params > w.params_at_start;
  const mine = w.your_computers ?? {};
  const join = async () => {
    setJoined(null);
    try { await put("/api/participant", { enabled: true }); setJoined("This PC now helps train MOTH between your own work."); void reloadPc(); }
    catch (e) { setJoined((e as Error).message); }
  };
  return <div className="grid gap-4 lg:grid-cols-3">
    <section aria-label="This week" className="rounded-xl border border-border bg-surface p-3 text-xs">
      <h2 className="mb-2 flex items-center gap-1.5 font-medium"><CalendarDays className="size-3.5 text-accent" /> This week</h2>
      <ul className="space-y-1 text-muted">
        <li><span className="text-fg">{tried}</span> training runs finished, <span className="text-fg">{promoted.length}</span> made MOTH better and went live</li>
        {grown && <li>Grew from <span className="text-fg">{short(w.params_at_start)}</span> to <span className="text-fg">{short(w.current.params)}</span> parameters</li>}
        {w.current && <li>Now serving <span className="text-fg">MOTH {w.current.model_version ?? `v${w.current.version}`}</span></li>}
        <li>{mine.count ? <>Your {mine.count === 1 ? "computer" : `${mine.count} computers`} trained for <span className="text-fg">{mine.hours} h</span> ({mine.jobs} jobs)</>
          : "None of your computers trained this week."}</li>
      </ul>
    </section>
    <section aria-label="MOTH's answers" className="rounded-xl border border-border bg-surface p-3 text-xs lg:col-span-2">
      <h2 className="mb-1 flex items-center gap-1.5 font-medium"><Sparkles className="size-3.5 text-accent" /> How MOTH answers now</h2>
      {w.examples?.length ? <><p className="text-faint">The same questions, before and after its last upgrade. MOTH is still young: expect rough answers.</p>
        <SideBySide rows={w.examples.slice(0, 3)} /></>
        : <Friendly text="Example answers appear here after MOTH's next upgrade." />}
    </section>
    {pc?.available && !pc?.enabled && <section aria-label="Train on this PC" className="flex flex-wrap items-center gap-3 rounded-xl border border-accent/40 bg-accent-soft p-3 text-xs lg:col-span-3">
      <Cpu className="size-4 text-accent" />
      <span className="min-w-0 flex-1"><span className="block text-fg">Help MOTH learn on this PC</span>
        <span className="text-muted">{pc.nvidia_gpu && !pc.gpu_usable ? `Trains on the CPU between your own work. For your ${pc.nvidia_gpu}, install the MOTH Worker from Network (much faster).`
          : "It trains between your own work and pauses when you need the computer. Stop at any time in Network."}</span>
        {joined && <span className="mt-1 block text-fg">{joined}</span>}</span>
      <Button size="sm" onClick={() => void join()}>Train on this PC</Button>
      {pc.nvidia_gpu && !pc.gpu_usable && <Button size="sm" variant="secondary" onClick={() => navigate("network")}>Use my GPU</Button>}
    </section>}
  </div>;
}

function Friendly({ text }: { text: string }) {
  return <div className="flex items-center gap-2 py-2 text-xs text-muted"><LivingMoth className="size-6 shrink-0 opacity-80" />{text}</div>;
}

/** 2.2: "Opened workspace demo-proj" five times in a row reads as one line with a count. */
export function collapseRepeats<T extends { message: string }>(items: T[]): (T & { times: number })[] {
  const out: (T & { times: number })[] = [];
  for (const it of items) {
    const last = out[out.length - 1];
    if (last && last.message === it.message) last.times += 1;
    else out.push({ ...it, times: 1 });
  }
  return out;
}

/** 2.5: what MOTH can really do at its current size, said plainly (it grows as it trains). */
export function honestCapability(params: number | null): string | null {
  if (params == null) return null;
  const m = params / 1e6;
  const size = m >= 1000 ? `${(m / 1000).toFixed(1)} billion` : `${m >= 10 ? Math.round(m) : m.toFixed(1)} million`;
  if (m < 50) return `MOTH is a small model (${size} parameters) that is still learning. It can continue text and short code patterns, but it cannot yet reliably answer questions, write working programs or carry out tasks on your PC. It improves as it trains.`;
  if (m < 1000) return `MOTH (${size} parameters) can complete and explain short code, but longer programs and multi-step tasks often need checking. Review what it changes.`;
  return `MOTH has ${size} parameters. Review what it changes before you rely on it.`;
}

function Honest({ params }: { params: number | null }) {
  const text = honestCapability(params);
  if (!text) return null;
  return <p role="note" className="rounded-xl border border-border bg-surface px-3 py-2 text-xs text-muted">
    <span className="font-medium text-fg">What MOTH can do today: </span>{text}</p>;
}
