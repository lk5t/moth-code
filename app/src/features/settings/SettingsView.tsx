import { useEffect, useState } from "react";
import { Info, RotateCcw, Shield } from "lucide-react";
import { appStore } from "@/lib/app-state";
import { useAccount } from "@/lib/account";
import { get, put, restartBackend } from "@/lib/backend";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { AccountSection } from "@/features/account/AccountSection";
import { UsageSection } from "@/features/billing/UsageSection";
import { ReferralsSection } from "@/features/billing/ReferralsSection";
import { IntelligenceSection } from "@/features/intelligence/IntelligenceSection";
import { OnDeviceSection } from "@/features/intelligence/OnDeviceSection";
import { UpdatesSection } from "./UpdatesSection";
import { ConnectionSection } from "./ConnectionSection";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

/** Settings in a few plain groups instead of one long page (0.5.4). */
const TABS = ["Account", "Privacy & AI", "Plan & referrals", "Code agent", "Updates & about"] as const;
type Tab = (typeof TABS)[number];

interface Permissions {
  auto_write: boolean;
  auto_execute: boolean;
  auto_git_commit: boolean;
}
const DEFAULT_PERMS: Permissions = { auto_write: true, auto_execute: true, auto_git_commit: false };

export function Row({ title, desc, children }: { title: string; desc?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-6 border-b border-border py-3 last:border-0">
      <div>
        <div className="text-[13px] text-fg">{title}</div>
        {desc && <div className="mt-0.5 text-xs text-muted">{desc}</div>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

export function SettingsView() {
  const owner = useAccount((s) => s.user?.role === "owner");
  const [perms, setPerms] = useState<Permissions>(DEFAULT_PERMS);
  const [system, setSystem] = useState<any>(null);
  const [version, setVersion] = useState("");
  const [tab, setTab] = useState<Tab>("Account");

  useEffect(() => {
    get<Record<string, any>>("/api/settings").then((s) => setPerms({ ...DEFAULT_PERMS, ...(s.permissions ?? {}) }));
    get("/api/system").then(setSystem).catch(() => {});
    get<{ version: string }>("/api/health").then((h) => setVersion(h.version));
  }, []);

  const setPerm = (k: keyof Permissions, v: boolean) => {
    const next = { ...perms, [k]: v };
    setPerms(next);
    put("/api/settings", { permissions: next });
  };

  return (
    <div className="h-full overflow-auto">
      <Tabs value={tab} onValueChange={(value) => setTab(value as Tab)} className="mx-auto flex max-w-5xl flex-col gap-3 p-3 animate-rise sm:p-5">
        <header className="flex items-center justify-between gap-3"><h1 className="text-lg font-semibold">Settings</h1>{owner && <Button size="sm" variant="secondary" onClick={() => appStore.setState({view:"owner"})}>Administration</Button>}</header>
        <TabsList aria-label="Settings sections">
          {TABS.map((t) => (
            <TabsTrigger key={t} value={t}>{t}</TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value={tab} className="flex flex-col gap-3">
        {tab === "Account" && <><AccountSection /><ConnectionSection /></>}
        {tab === "Privacy & AI" && <><IntelligenceSection /><OnDeviceSection /></>}
        {tab === "Plan & referrals" && <><UsageSection /><ReferralsSection /></>}
        {tab === "Updates & about" && <UpdatesSection />}

        {tab === "Code agent" && <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Shield className="size-4 text-accent" />Agent permissions</CardTitle>
            <CardDescription>
              MOTH only works inside folders you open as workspaces. Deleting files, destructive commands, publishing
              (e.g. git push), network access and anything outside the workspace always require your approval.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Row title="Create and edit files without asking" desc="Inside the open workspace only.">
              <Switch checked={perms.auto_write} onCheckedChange={(v) => setPerm("auto_write", v)} />
            </Row>
            <Row title="Run ordinary commands without asking" desc="Builds and tests. Destructive commands still ask.">
              <Switch checked={perms.auto_execute} onCheckedChange={(v) => setPerm("auto_execute", v)} />
            </Row>
            <Row title="Make local Git commits without asking">
              <Switch checked={perms.auto_git_commit} onCheckedChange={(v) => setPerm("auto_git_commit", v)} />
            </Row>
          </CardContent>
        </Card>}

        {tab === "Updates & about" && <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Info className="size-4 text-accent" />About</CardTitle>
          </CardHeader>
          <CardContent className="text-xs text-muted">
            <Row title={`MOTH Code ${version}`} desc="Independent AI coding agent with its own neural network.">
              <Button variant="secondary" size="sm" onClick={() => restartBackend().then(() => location.reload())}>
                <RotateCcw /> Restart backend
              </Button>
            </Row>
            {system && (
              <div className="mt-3 grid grid-cols-[140px_1fr] gap-y-1.5">
                <span>Platform</span><span className="text-fg">{system.platform}</span>
                <span>CPU threads</span><span className="text-fg">{system.cpu_count}</span>
                <span>PyTorch</span><span className="text-fg">{system.torch ?? <Badge variant="danger">not available</Badge>}</span>
                <span>GPU</span>
                <span className="text-fg">
                  {system.gpus?.length ? system.gpus.map((g: any) => `${g.name} (${g.memory_gb} GB)`).join(", ") : "No CUDA GPU detected — CPU mode"}
                </span>
                <span>Git</span><span className="text-fg">{system.git ? "available" : "not found"}</span>
              </div>
            )}
          </CardContent>
        </Card>}
        </TabsContent>
      </Tabs>
    </div>
  );
}
