import { useEffect, useState } from "react";
import { Activity, Crown, RefreshCw } from "lucide-react";
import { serverApi, withReauth, useAccount } from "@/lib/account";
import { askPassword } from "@/features/account/reauth";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input, Label, Textarea } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { EmptyState } from "@/components/ui/empty";
import { formatNumber, timeAgo } from "@/lib/utils";
import { ModelsPanel, ServerPanel, UpdatesPanel, WorkersPanel } from "./ops";

type Any = Record<string, any>;

/** Sensitive Owner actions: the server may ask for the password again (HTTP 428). */
const secure = <T,>(fn: () => Promise<T>) => withReauth(fn, askPassword);

function useAdmin<T>(path: string, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => serverApi<T>(path).then((d) => { setData(d); setError(null); }).catch((e) => setError(e.message));
  useEffect(() => { load(); }, deps);
  return { data, error, load, setData };
}

function Msg({ m }: { m: { ok: boolean; text: string } | null }) {
  return m ? <div className={m.ok ? "text-xs text-success" : "text-xs text-danger"}>{m.text}</div> : null;
}

function useAction() {
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const run = async (fn: () => Promise<unknown>, ok: string, after?: () => void) => {
    setMsg(null);
    try {
      await secure(fn);
      setMsg({ ok: true, text: ok });
      after?.();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
  };
  return { msg, run };
}

const Stat = ({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) => (
  <div className="rounded-lg border border-border bg-bg px-3 py-2.5">
    <div className="text-[10.5px] uppercase tracking-wider text-faint">{label}</div>
    <div className="mt-0.5 font-mono text-base">{value}</div>
    {sub && <div className="text-[11px] text-muted">{sub}</div>}
  </div>
);

function Overview() {
  const { data: o, load } = useAdmin<Any>("/v1/admin/overview");
  if (!o) return null;
  const bytes = (n: number | null) => {
    if (n == null) return "—";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    let v = n;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return `${v.toFixed(i ? 1 : 0)} ${units[i]}`;
  };
  return (
    <div className="flex flex-col gap-4">
      <div className="flex justify-end"><Button size="sm" variant="ghost" onClick={load}><RefreshCw /> Refresh</Button></div>
      <div className="grid grid-cols-4 gap-3">
        <Stat label="Users" value={o.users.total} sub={`${o.users.verified} verified · ${o.users.new_30d} new (30d)`} />
        <Stat label="Subscriptions" value={o.billing.active_subscriptions} sub={o.billing.payments_configured ? "payments live" : "payments not configured"} />
        <Stat label="Cloud tokens (month)" value={formatNumber(o.billing.tokens_used_this_month, 1)} sub={`${formatNumber(o.billing.credits_outstanding, 1)} credits outstanding`} />
        <Stat label="Pending rewards" value={o.billing.pending_rewards} />
        <Stat label="Workers online" value={`${o.training.workers_online}/${o.training.workers_total}`} sub={o.training.configured ? `round ${o.training.round} · ckpt v${o.training.checkpoint_version}` : "training not started"} />
        <Stat label="Jobs" value={Object.entries(o.training.jobs).map(([k, v]) => `${k} ${v}`).join(" · ") || "none"} />
        <Stat label="Deployed model" value={o.models.deployed ? `v${o.models.deployed.version}` : "none"} sub={o.models.deployed ? `${o.models.deployed.name}${o.models.cloud_inference_enabled ? "" : " · inference disabled"}` : "MOTH Cloud has nothing to serve"} />
        <Stat label="Sessions" value={o.users.active_sessions} sub={`plans: ${Object.entries(o.users.by_plan).map(([k, v]) => `${k} ${v}`).join(", ")}`} />
      </div>
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><Activity className="size-4 text-accent" />System health</CardTitle></CardHeader>
        <CardContent className="grid grid-cols-[180px_1fr] gap-y-1.5 text-xs text-muted">
          <span>Uptime</span><span className="text-fg">{Math.round(o.system.uptime_seconds / 3600)} h</span>
          <span>Database</span><span className="text-fg">{o.system.database} {o.system.database_bytes != null && `· ${bytes(o.system.database_bytes)}`}</span>
          <span>Model & data storage</span><span className="text-fg">{bytes(o.system.storage_bytes)} · coordinator {bytes(o.system.coordinator_bytes)}</span>
          <span>Disk</span><span className="text-fg">{bytes(o.system.disk_free_bytes)} free of {bytes(o.system.disk_total_bytes)}</span>
          <span>Email</span><span className="text-fg">{o.system.email === "smtp" ? "SMTP" : "development outbox (no real emails sent)"}</span>
          <span>Public URL</span><span className="text-fg">{o.system.public_url}</span>
        </CardContent>
      </Card>
    </div>
  );
}

function Users() {
  const [q, setQ] = useState("");
  const { data, load } = useAdmin<Any[]>(`/v1/admin/users?q=${encodeURIComponent(q)}`, [q]);
  const [sel, setSel] = useState<number | null>(null);
  const { data: detail, load: loadDetail } = useAdmin<Any>(sel ? `/v1/admin/users/${sel}` : "/v1/admin/overview", [sel]);
  const [credit, setCredit] = useState({ amount: "", reason: "" });
  const [grant, setGrant] = useState({ plan: "pro", days: "30" });
  const { msg, run } = useAction();
  const refresh = () => { load(); loadDetail(); };
  return (
    <div className="grid grid-cols-[1fr_1.1fr] gap-4">
      <Card>
        <CardContent className="flex flex-col gap-2">
          <Input placeholder="Search username or email" value={q} onChange={(e) => setQ(e.target.value)} />
          <div className="max-h-[60vh] space-y-1 overflow-auto">
            {data?.map((u) => (
              <button key={u.id} onClick={() => setSel(u.id)} className={`flex w-full cursor-pointer items-center justify-between rounded border px-2.5 py-1.5 text-left text-xs ${sel === u.id ? "border-accent/60" : "border-border"} hover:border-border-strong`}>
                <span className="truncate">@{u.username} <span className="text-faint">{u.email}</span></span>
                <span className="flex shrink-0 gap-1">
                  {u.role !== "user" && <Badge variant="accent">{u.role}</Badge>}
                  {u.status !== "active" && <Badge variant="danger">{u.status}</Badge>}
                  {u.role !== "owner" && <Badge>{u.plan_code}</Badge>}
                </span>
              </button>
            ))}
          </div>
        </CardContent>
      </Card>
      {sel && detail?.user ? (
        <Card>
          <CardHeader>
            <CardTitle>@{detail.user.username} {detail.user.role === "owner" && <Badge variant="accent">Owner</Badge>}</CardTitle>
            <CardDescription>{detail.user.email} · joined {timeAgo(detail.user.created_at)} · {detail.sessions} active sessions · {detail.workers.length} workers</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 text-xs">
            <div className="text-muted">
              Plan <span className="text-fg">{detail.summary.plan.name}</span> · {detail.summary.unlimited ? "unlimited" : `${formatNumber(detail.summary.period.used, 1)} / ${formatNumber(detail.summary.period.allowance, 1)} tokens`} · credits <span className="text-fg">{formatNumber(detail.summary.credits, 1)}</span>
            </div>
            {detail.user.role !== "owner" && (
              <>
                <div className="flex items-end gap-2">
                  <div><Label>Credits (±tokens)</Label><Input className="mt-1 w-28" value={credit.amount} onChange={(e) => setCredit({ ...credit, amount: e.target.value })} /></div>
                  <div className="flex-1"><Label>Reason (audited)</Label><Input className="mt-1" value={credit.reason} onChange={(e) => setCredit({ ...credit, reason: e.target.value })} /></div>
                  <Button size="sm" disabled={!credit.amount || credit.reason.length < 3} onClick={() => run(() => serverApi(`/v1/admin/users/${sel}/credits`, { method: "POST", json: { amount: Number(credit.amount), reason: credit.reason } }), "Credits adjusted.", refresh)}>Apply</Button>
                </div>
                <div className="flex items-end gap-2">
                  <div><Label>Grant plan</Label>
                    <select className="mt-1 h-8 rounded-md border border-border bg-bg px-2 text-[13px]" value={grant.plan} onChange={(e) => setGrant({ ...grant, plan: e.target.value })}>
                      {["free", "pro", "max"].map((p) => <option key={p}>{p}</option>)}
                    </select>
                  </div>
                  <div><Label>Days</Label><Input className="mt-1 w-20" value={grant.days} onChange={(e) => setGrant({ ...grant, days: e.target.value })} /></div>
                  <Button size="sm" variant="secondary" onClick={() => run(() => serverApi(`/v1/admin/users/${sel}/plan`, { method: "POST", json: { plan: grant.plan, days: Number(grant.days) } }), "Plan granted.", refresh)}>Grant</Button>
                </div>
                <div className="flex gap-2">
                  <Button size="sm" variant="secondary" onClick={() => run(() => serverApi(`/v1/admin/users/${sel}/role`, { method: "POST", json: { role: detail.user.role === "admin" ? "user" : "admin" } }), "Role changed.", refresh)}>
                    {detail.user.role === "admin" ? "Remove admin" : "Make admin"}
                  </Button>
                  <Button size="sm" variant={detail.user.status === "active" ? "danger" : "secondary"} onClick={() => run(() => serverApi(`/v1/admin/users/${sel}/status`, { method: "POST", json: { status: detail.user.status === "active" ? "suspended" : "active" } }), "Status changed.", refresh)}>
                    {detail.user.status === "active" ? "Suspend" : "Reactivate"}
                  </Button>
                </div>
              </>
            )}
            <Msg m={msg} />
            <details><summary className="cursor-pointer text-muted">Credit ledger ({detail.ledger.length})</summary>
              <div className="mt-1 space-y-0.5">{detail.ledger.map((l: Any) => <div key={l.id} className="flex justify-between"><span>{l.kind}{l.note ? ` — ${l.note}` : ""}</span><span className="font-mono">{l.amount > 0 ? "+" : ""}{l.amount} → {l.balance_after}</span></div>)}</div>
            </details>
          </CardContent>
        </Card>
      ) : <EmptyState title="Select a user" />}
    </div>
  );
}

function Plans() {
  const { data, load } = useAdmin<Any[]>("/v1/admin/plans");
  const { msg, run } = useAction();
  const [edit, setEdit] = useState<Record<string, Any>>({});
  if (!data) return null;
  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-muted">Prices are shown to users; checkout stays off until a provider price id is set, checkout is enabled, and Stripe credentials are configured on the server.</p>
      {data.map((p) => {
        const e = { ...p, ...(edit[p.code] ?? {}) };
        const set = (k: string, v: unknown) => setEdit({ ...edit, [p.code]: { ...(edit[p.code] ?? {}), [k]: v } });
        return (
          <Card key={p.code}>
            <CardContent className="grid grid-cols-6 items-end gap-2 text-xs">
              <div><Label>{p.code}</Label><Input className="mt-1" value={e.name} onChange={(ev) => set("name", ev.target.value)} /></div>
              <div><Label>Price (cents/mo)</Label><Input className="mt-1" type="number" value={e.price_cents} onChange={(ev) => set("price_cents", Number(ev.target.value))} /></div>
              <div><Label>Tokens / month</Label><Input className="mt-1" type="number" value={e.monthly_tokens} onChange={(ev) => set("monthly_tokens", Number(ev.target.value))} /></div>
              <div><Label>Provider price id</Label><Input className="mt-1" value={e.provider_price_id ?? ""} onChange={(ev) => set("provider_price_id", ev.target.value)} disabled={p.code === "free"} /></div>
              <label className="flex items-center gap-2 pb-2"><Switch checked={!!e.checkout_enabled} disabled={p.code === "free"} onCheckedChange={(v) => set("checkout_enabled", v)} />Checkout</label>
              <Button size="sm" disabled={!edit[p.code]} onClick={() => run(() => serverApi(`/v1/admin/plans/${p.code}`, { method: "PUT", json: edit[p.code] }), `${p.name} saved.`, () => { setEdit({ ...edit, [p.code]: undefined as never }); load(); })}>Save</Button>
            </CardContent>
          </Card>
        );
      })}
      <Msg m={msg} />
    </div>
  );
}

function Referrals() {
  const { data, load } = useAdmin<Any>("/v1/admin/referrals");
  const { msg, run } = useAction();
  const [rules, setRules] = useState<Any | null>(null);
  useEffect(() => { if (data) setRules(data.rules); }, [data]);
  if (!data || !rules) return null;
  const num = (k: string, label: string) => (
    <div key={k}><Label>{label}</Label><Input className="mt-1" type="number" value={rules[k]} onChange={(e) => setRules({ ...rules, [k]: Number(e.target.value) })} /></div>
  );
  const review = data.referrals.filter((r: Any) => r.status === "review");
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader><CardTitle>Reward rules</CardTitle><CardDescription>Usage credits only. Rewards require a verified paid invoice or verified training work.</CardDescription></CardHeader>
        <CardContent className="grid grid-cols-4 gap-3 text-xs">
          {num("user_reward_tokens", "Referral reward (tokens)")}
          {num("qualifying_min_amount_cents", "Minimum payment (cents)")}
          {num("gpu_reward_tokens_per_job", "GPU reward per verified job")}
          {num("gpu_min_verified_jobs", "GPU: min verified jobs")}
          {num("pending_days", "Pending period (days)")}
          {num("max_user_rewards_per_month", "Max referral rewards / month")}
          {num("max_gpu_reward_tokens_per_month", "Max GPU tokens / month")}
          {num("lifetime_cap_tokens", "Lifetime cap (tokens)")}
          <label className="flex items-center gap-2"><Switch checked={rules.enabled} onCheckedChange={(v) => setRules({ ...rules, enabled: v })} />Referrals enabled</label>
          <label className="col-span-2 flex items-center gap-2"><Switch checked={rules.hold_same_ip_for_review} onCheckedChange={(v) => setRules({ ...rules, hold_same_ip_for_review: v })} />Hold same-IP referrals for review</label>
          <Button size="sm" onClick={() => run(() => serverApi("/v1/admin/referral-rules", { method: "PUT", json: rules }), "Rules saved.", load)}>Save rules</Button>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Review queue ({review.length})</CardTitle></CardHeader>
        <CardContent className="space-y-1 text-xs">
          {!review.length && <div className="text-muted">Nothing to review.</div>}
          {review.map((r: Any) => (
            <div key={r.id} className="flex items-center justify-between rounded border border-border px-2.5 py-1.5">
              <span>@{r.referrer} → @{r.referred} <span className="text-faint">{JSON.parse(r.flags).join(", ")}</span></span>
              <span className="flex gap-1">
                <Button size="sm" variant="secondary" onClick={() => run(() => serverApi(`/v1/admin/referrals/${r.id}/approve`, { method: "POST" }), "Approved.", load)}>Approve</Button>
                <Button size="sm" variant="danger" onClick={() => run(() => serverApi(`/v1/admin/referrals/${r.id}/reject`, { method: "POST", json: { reason: "rejected by owner" } }), "Rejected.", load)}>Reject</Button>
              </span>
            </div>
          ))}
          <Button size="sm" variant="ghost" onClick={() => run(() => serverApi("/v1/admin/rewards/process", { method: "POST" }), "Matured rewards processed.", load)}>Process matured rewards now</Button>
          <Msg m={msg} />
        </CardContent>
      </Card>
    </div>
  );
}

function Policy() {
  const { data } = useAdmin<Any>("/v1/admin/policy");
  const [p, setP] = useState<Any | null>(null);
  const [rules, setRules] = useState("[]");
  const { msg, run } = useAction();
  useEffect(() => { if (data) { setP(data); setRules(JSON.stringify(data.content_rules, null, 2)); } }, [data]);
  if (!p) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Content policy (server-side)</CardTitle>
        <CardDescription>Applied to every MOTH Cloud request for every user. Ships with no topic restrictions. Operational protections (redaction, permissions) are separate and always on.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div><Label>System prompt (MOTH persona)</Label><Textarea className="mt-1" rows={3} value={p.system_prompt} onChange={(e) => setP({ ...p, system_prompt: e.target.value })} /></div>
        <div><Label>Rules (JSON)</Label><Textarea className="mt-1 font-mono text-xs" rows={10} value={rules} onChange={(e) => setRules(e.target.value)} spellCheck={false} /></div>
        <div className="flex items-center gap-2">
          <Button onClick={() => run(async () => serverApi("/v1/admin/policy", { method: "PUT", json: { ...p, content_rules: JSON.parse(rules) } }), "Policy saved and active.")}>Save policy</Button>
          <Msg m={msg} />
        </div>
      </CardContent>
    </Card>
  );
}

const FLAG_LABELS: Record<string, string> = {
  cloud_inference_enabled: "MOTH Cloud inference (only with MOTH-operated GPU capacity)",
  registration_open: "Open registration",
  referrals_enabled: "Referral program",
  training_enrollment_open: "GPU worker enrollment",
  allow_cpu_workers: "Allow CPU workers (development only)",
  auto_deploy_models: "Auto-deploy candidates that pass evaluation",
};

function Flags() {
  const { data, load } = useAdmin<Any>("/v1/admin/config");
  const { msg, run } = useAction();
  if (!data) return null;
  return (
    <Card>
      <CardContent className="flex flex-col">
        {Object.entries(data.feature_flags).map(([k, v]) => (
          <div key={k} className="flex items-center justify-between border-b border-border py-2.5 text-[13px] last:border-0">
            <span>{FLAG_LABELS[k] ?? k}</span>
            <Switch checked={!!v} onCheckedChange={(val) => run(() => serverApi("/v1/admin/config/flags", { method: "PUT", json: { [k]: val } }), "Flag updated.", load)} />
          </div>
        ))}
        <Msg m={msg} />
      </CardContent>
    </Card>
  );
}

function Audit() {
  const [action, setAction] = useState("");
  const { data } = useAdmin<Any[]>(`/v1/admin/audit?limit=300&action=${encodeURIComponent(action)}`, [action]);
  return (
    <Card>
      <CardContent className="flex flex-col gap-2">
        <Input placeholder="Filter by action prefix (e.g. admin. or auth.login)" value={action} onChange={(e) => setAction(e.target.value)} />
        <div className="max-h-[60vh] overflow-auto text-[11px]">
          {data?.map((a) => (
            <div key={a.id} className="grid grid-cols-[120px_200px_1fr] gap-2 border-b border-border py-1">
              <span className="text-faint">{new Date(a.ts * 1000).toLocaleString()}</span>
              <span className="font-mono text-[#ff6b75]">{a.action}</span>
              <span className="truncate text-muted">{a.username ? `@${a.username} · ` : ""}{a.target ?? ""} {Object.keys(a.detail).length ? JSON.stringify(a.detail) : ""} {a.ip ? `· ${a.ip}` : ""}</span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function Billing() {
  return <div className="flex flex-col gap-6"><Plans /><Referrals /></div>;
}

function PolicyAndFlags() {
  return <div className="flex flex-col gap-6"><Flags /><Policy /></div>;
}

export function OwnerDashboard() {
  const role = useAccount((s) => s.user?.role);
  if (role !== "owner") return <EmptyState title="Owner Dashboard">Available to the MOTH Owner account only.</EmptyState>;
  const tabs: [string, string, React.ComponentType][] = [
    ["overview", "Overview", Overview], ["server", "Server", ServerPanel], ["updates", "Updates", UpdatesPanel],
    ["models", "AI models", ModelsPanel], ["workers", "Workers", WorkersPanel], ["users", "Users", Users],
    ["billing", "Plans & referrals", Billing], ["settings", "Policy & flags", PolicyAndFlags], ["audit", "Audit log", Audit],
  ];
  return (
    <div className="h-full overflow-auto">
      <div className="mx-auto flex max-w-6xl flex-col gap-4 p-8 animate-rise">
        <h1 className="flex items-center gap-2 text-lg font-semibold"><Crown className="size-5 text-accent" />Owner Dashboard</h1>
        <Tabs defaultValue="overview">
          <TabsList className="mb-4 border-b border-border">
            {tabs.map(([v, l]) => <TabsTrigger key={v} value={v}>{l}</TabsTrigger>)}
          </TabsList>
          {tabs.map(([v, , C]) => <TabsContent key={v} value={v}><C /></TabsContent>)}
        </Tabs>
      </div>
    </div>
  );
}
