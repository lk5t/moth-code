import { useEffect, useState } from "react";
import { Gauge, Receipt } from "lucide-react";
import { serverApi, useAccount } from "@/lib/account";
import { openExternal } from "@/lib/external";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { cn, formatNumber } from "@/lib/utils";

interface Plan {
  code: string;
  name: string;
  price_cents: number;
  currency: string;
  monthly_tokens: number;
  priority: number;
  checkout_available: boolean;
}
interface Summary {
  plan: { code: string; name: string };
  unlimited: boolean;
  period: { start: number; end: number; allowance: number; used: number; remaining: number | null };
  credits: number;
  renews_at: number;
  subscription: { status: string; provider: string; cancel_at_period_end: boolean; current_period_end: number } | null;
}
interface UsageEvent {
  id: number;
  created_at: number;
  model: string | null;
  input_tokens: number;
  output_tokens: number;
  charged_allowance: number;
  charged_credits: number;
  unmetered: boolean;
}
interface LedgerRow {
  id: number;
  created_at: number;
  amount: number;
  kind: string;
  note: string | null;
}

const date = (t: number) => new Date(t * 1000).toLocaleDateString();

export function UsageSection() {
  const user = useAccount((s) => s.user);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [tx, setTx] = useState<{ usage: UsageEvent[]; ledger: LedgerRow[] }>({ usage: [], ledger: [] });
  const [msg, setMsg] = useState<string | null>(null);

  const load = () => {
    serverApi<Plan[]>("/v1/billing/plans", { token: null }).then(setPlans).catch(() => {});
    if (user) {
      serverApi<Summary>("/v1/billing/summary").then(setSummary).catch(() => {});
      serverApi<{ usage: UsageEvent[]; ledger: LedgerRow[] }>("/v1/billing/transactions?limit=50").then(setTx).catch(() => {});
    }
  };
  useEffect(load, [user?.id]);
  if (!user) return null;

  const act = async (fn: () => Promise<{ url?: string } | undefined>) => {
    setMsg(null);
    try {
      const r = await fn();
      if (r?.url) await openExternal(r.url);
      load();
    } catch (e) {
      setMsg((e as Error).message);
    }
  };
  const p = summary?.period;
  const pct = p && p.allowance ? (p.used / p.allowance) * 100 : 0;
  const anyCheckout = plans.some((x) => x.checkout_available);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Gauge className="size-4 text-accent" />Plan & usage</CardTitle>
        <CardDescription>
          Usage applies to MOTH Cloud inference only. Local models on this PC are free and unlimited.
          {!anyCheckout && " Paid plans are not available for purchase yet."}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {summary && (
          <div className="rounded-lg border border-border p-3">
            <div className="flex items-center justify-between text-xs">
              <span className="flex items-center gap-2 text-sm font-medium">
                {summary.plan.name}
                {summary.unlimited && <Badge variant="accent">Owner · unlimited</Badge>}
                {summary.subscription?.status === "past_due" && <Badge variant="warning">payment failed</Badge>}
                {summary.subscription?.cancel_at_period_end && <Badge>ends {date(summary.subscription.current_period_end)}</Badge>}
              </span>
              <span className="text-muted">{summary.unlimited ? "No limits" : `Renews ${date(summary.renews_at)}`}</span>
            </div>
            {!summary.unlimited && p && (
              <>
                <Progress value={pct} className="mt-3" />
                <div className="mt-1.5 flex justify-between text-[11px] text-muted">
                  <span>{formatNumber(p.used, 1)} of {formatNumber(p.allowance, 1)} tokens used</span>
                  <span className="text-fg">{formatNumber(p.remaining ?? 0, 1)} remaining</span>
                </div>
              </>
            )}
            <div className="mt-2 text-[11px] text-muted">
              Earned credits: <span className="text-fg">{formatNumber(summary.credits, 1)}</span> tokens (used after your monthly allowance)
            </div>
          </div>
        )}
        {!summary?.unlimited && (
          <div className="grid grid-cols-3 gap-2">
            {plans.map((pl) => {
              const current = summary?.plan.code === pl.code;
              return (
                <div key={pl.code} className={cn("flex flex-col gap-1 rounded-lg border border-border p-3", current && "border-accent/60 shadow-glow")}>
                  <div className="text-[13px] font-medium">{pl.name}</div>
                  <div className="text-lg font-semibold">
                    {pl.price_cents ? `$${(pl.price_cents / 100).toFixed(2)}` : "Free"}
                    <span className="text-xs font-normal text-muted">{pl.price_cents ? " / month" : ""}</span>
                  </div>
                  <div className="text-[11px] text-muted">{formatNumber(pl.monthly_tokens, 1)} cloud tokens / month{pl.priority > 1 ? " · priority" : ""}</div>
                  {current ? (
                    <Badge variant="success" className="mt-1 self-start">current</Badge>
                  ) : (
                    pl.code !== "free" && (
                      <Button size="sm" className="mt-1" disabled={!pl.checkout_available}
                        onClick={() => act(() => serverApi("/v1/billing/checkout", { method: "POST", json: { plan: pl.code } }))}>
                        {pl.checkout_available ? "Upgrade" : "Coming soon"}
                      </Button>
                    )
                  )}
                </div>
              );
            })}
          </div>
        )}
        {summary?.subscription?.provider === "stripe" && (
          <div className="flex gap-2">
            <Button size="sm" variant="secondary" onClick={() => act(() => serverApi("/v1/billing/portal", { method: "POST" }))}>Manage billing</Button>
            {!summary.subscription.cancel_at_period_end && (
              <Button size="sm" variant="ghost"
                onClick={() => confirm("Cancel at the end of the billing period?") && act(() => serverApi("/v1/billing/subscription/cancel", { method: "POST" }))}>
                Cancel subscription
              </Button>
            )}
          </div>
        )}
        <details>
          <summary className="flex cursor-pointer items-center gap-1.5 text-xs text-muted"><Receipt className="size-3" />Transaction history</summary>
          <div className="mt-2 max-h-64 space-y-1 overflow-auto text-[11px]">
            {tx.ledger.map((l) => (
              <div key={`l${l.id}`} className="flex justify-between rounded border border-border px-2 py-1">
                <span>{l.kind.replace(/_/g, " ")}{l.note ? ` — ${l.note}` : ""}</span>
                <span className={l.amount >= 0 ? "text-success" : "text-muted"}>{l.amount >= 0 ? "+" : ""}{formatNumber(l.amount, 1)} · {date(l.created_at)}</span>
              </div>
            ))}
            {tx.usage.map((u) => (
              <div key={`u${u.id}`} className="flex justify-between rounded border border-border px-2 py-1 text-muted">
                <span>{u.model ?? "cloud"} · {u.input_tokens} in / {u.output_tokens} out</span>
                <span>{u.unmetered ? "unmetered" : `${formatNumber(u.charged_allowance + u.charged_credits, 1)} tokens`} · {date(u.created_at)}</span>
              </div>
            ))}
            {!tx.ledger.length && !tx.usage.length && <div className="text-muted">No transactions yet.</div>}
          </div>
        </details>
        {msg && <div className="text-xs text-danger">{msg}</div>}
      </CardContent>
    </Card>
  );
}
