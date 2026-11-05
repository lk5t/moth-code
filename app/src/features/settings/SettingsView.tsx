import { useEffect, useState } from "react";
import { Info, RotateCcw, Shield } from "lucide-react";
import { get, put, restartBackend } from "@/lib/backend";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { settingsSections } from "./sections";

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
  const [perms, setPerms] = useState<Permissions>(DEFAULT_PERMS);
  const [system, setSystem] = useState<any>(null);
  const [version, setVersion] = useState("");

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
      <div className="mx-auto flex max-w-3xl flex-col gap-5 p-8 animate-rise">
        <h1 className="text-lg font-semibold">Settings</h1>

        <Card>
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
        </Card>

        {settingsSections.map((S, i) => <S key={i} />)}

        <Card>
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
        </Card>
      </div>
    </div>
  );
}
