/**
 * 1.0 home screen: a greeting, what MOTH is doing right now, today's progress, recent projects and chats,
 * and a live activity feed. Everything shown is measured; nothing is decorative guesswork.
 */
import { useEffect, useState } from "react";
import { Brain, FolderGit2, FolderOpen, MessageSquare, Plus, Sparkles, Zap } from "lucide-react";
import { useAccount } from "@/lib/account";
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

type Any = Record<string, any>;

export function greeting(hour: number): string {
  return hour < 5 ? "Good night" : hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
}

function Tile({ icon, label, value, live }: { icon: React.ReactNode; label: string; value: number | string | null; live?: boolean }) {
  return <div className="lift relative overflow-hidden rounded-xl border border-border bg-surface px-3 py-2.5">
    {live && <span className="pointer-events-none absolute -right-5 -top-5 size-16 rounded-full bg-accent/20 blur-xl" />}
    <div className="flex items-center gap-1.5 text-[10.5px] uppercase tracking-wider text-faint [&_svg]:size-3.5 [&_svg]:text-accent">{icon}{label}{live && <span className="live-dot ml-auto" />}</div>
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
          </div>
        </div>
      </header>

      <CloneGitHub />

      <section aria-label="Today" className="stagger grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile icon={<Zap />} label="Tokens learned (this run)" value={typeof m.tokens_seen === "number" ? m.tokens_seen : null} live={!!running} />
        <Tile icon={<Brain />} label="Parameters" value={typeof p?.current?.params === "number" ? p.current.params : null} />
        <Tile icon={<Sparkles />} label="Workers online" value={typeof p?.network?.workers_online === "number" ? p.network.workers_online : null} live={(p?.network?.workers_online ?? 0) > 0} />
        <Tile icon={<MessageSquare />} label="Your chats" value={chats?.length ?? null} />
      </section>

      {running && <section aria-label="MOTH's progress" className="grid gap-3 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <StageMeter loss={m.val_loss ?? m.train_loss} per={running.loss_per === "token" ? "token" : "byte"} />
        <button onClick={() => navigate("intelligence")} className="lift rounded-lg border border-border bg-bg p-3 text-left text-xs">
          <span className="text-faint">Live training</span>
          <span className="mt-1 block text-sm text-fg">{typeof m.fraction === "number" ? `${Math.round(m.fraction * 100)}% of this run` : "Starting…"}</span>
          <span className="mt-1 block text-accent">Watch it learn →</span>
        </button>
      </section>}

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
          {activity?.length ? <ol className="stagger max-h-64 space-y-1.5 overflow-auto">{activity.slice(0, 12).map((a) =>
            <li key={a.id} className="animate-message-in text-xs"><span className="text-fg">{a.message}</span> <span className="text-faint">· {timeAgo(a.ts)}</span></li>)}</ol>
            : <Friendly text="Quiet for now. Tasks, file changes and MOTH's news appear here as they happen." />}
        </section>
      </div>
    </div>
  </div>;
}

function Friendly({ text }: { text: string }) {
  return <div className="flex items-center gap-2 py-2 text-xs text-muted"><LivingMoth className="size-6 shrink-0 opacity-80" />{text}</div>;
}
