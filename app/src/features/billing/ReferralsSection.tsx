import { useEffect, useState } from "react";
import { Copy, Gift } from "lucide-react";
import { serverApi, useAccount } from "@/lib/account";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { formatNumber, timeAgo } from "@/lib/utils";

interface Dashboard {
  code: string;
  link: string;
  rules: { enabled: boolean; user_reward_tokens: number; pending_days: number; user_payment_rewards?: boolean };
  rules_text?: string[];
  referred_workers?: { name: string; compute: string; status: string; verified_jobs: number; trained_tokens: number; reputation: number; last_seen: number | null; earned: number }[];
  stats: { referred: number; qualified: number; pending_tokens: number; earned_tokens: number };
  referrals: { user: string; status: string; created_at: number }[];
  rewards: { id: number; kind: string; amount: number; status: string; available_at: number; reason: string | null; created_at: number }[];
}

const tone: Record<string, "success" | "warning" | "danger" | "default" | "accent"> = {
  credited: "success", rewarded: "success", pending: "accent", qualified: "accent", review: "warning",
  capped: "warning", reversed: "danger", rejected: "danger", registered: "default",
};

export function ReferralsSection() {
  const user = useAccount((s) => s.user);
  const [d, setD] = useState<Dashboard | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  useEffect(() => {
    if (user) serverApi<Dashboard>("/v1/referrals").then(setD).catch(() => setD(null));
  }, [user?.id]);
  if (!user || !d) return null;

  const copy = async (text: string, what: string) => {
    await navigator.clipboard.writeText(text).catch(() => {});
    setCopied(what);
    setTimeout(() => setCopied(null), 1500);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Gift className="size-4 text-accent" />Referrals</CardTitle>
        <CardDescription>
          Invite people to contribute a computer (CPU or GPU) to MOTH. You earn MOTH usage credits for the verified training
          work their workers do. Signing up alone earns nothing.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex gap-2">
          <Input readOnly value={d.code} className="w-36 text-center font-mono tracking-[0.2em]" />
          <Button variant="secondary" onClick={() => copy(d.code, "code")}><Copy /> {copied === "code" ? "Copied" : "Copy code"}</Button>
          <Input readOnly value={d.link} className="flex-1 text-xs" />
          <Button variant="secondary" onClick={() => copy(d.link, "link")}><Copy /> {copied === "link" ? "Copied" : "Copy link"}</Button>
        </div>
        <div className="grid grid-cols-4 gap-2">
          {[
            ["Invited", d.stats.referred],
            ["Workers", d.referred_workers?.length ?? 0],
            ["Pending", `${formatNumber(d.stats.pending_tokens, 1)}`],
            ["Earned", `${formatNumber(d.stats.earned_tokens, 1)}`],
          ].map(([k, v]) => (
            <div key={k as string} className="rounded-md border border-border bg-bg px-3 py-2">
              <div className="text-[10.5px] uppercase tracking-wider text-faint">{k}</div>
              <div className="mt-0.5 font-mono text-sm">{v}</div>
            </div>
          ))}
        </div>
        {d.referrals.length > 0 && (
          <div className="space-y-1 text-xs">
            {d.referrals.map((r, i) => (
              <div key={i} className="flex justify-between rounded border border-border px-2.5 py-1.5">
                <span>{r.user} <span className="text-faint">· joined {timeAgo(r.created_at)}</span></span>
                <Badge variant={tone[r.status]}>{r.status}</Badge>
              </div>
            ))}
          </div>
        )}
        {!!d.referred_workers?.length && (
          <div className="space-y-1 text-xs">
            <div className="text-[10.5px] uppercase tracking-wider text-faint">Workers you referred</div>
            {d.referred_workers.map((w, i) => (
              <div key={i} className="flex justify-between rounded border border-border px-2.5 py-1.5">
                <span>{w.name} <span className="text-faint">· {w.compute.toUpperCase()} · {w.verified_jobs} verified jobs · {(w.trained_tokens / 1e6).toFixed(2)}M tokens · reliability {Math.round(w.reputation * 100)}%{w.last_seen ? ` · seen ${timeAgo(w.last_seen)}` : ""}</span></span>
                <span className="flex items-center gap-2"><span className="font-mono">{formatNumber(w.earned, 1)}</span><Badge variant={w.status === "online" ? "success" : "default"}>{w.status}</Badge></span>
              </div>
            ))}
          </div>
        )}
        {!!d.rules_text?.length && (
          <details className="text-xs text-muted">
            <summary className="cursor-pointer">How rewards work</summary>
            <ul className="mt-1.5 list-disc space-y-1 pl-4">{d.rules_text.map((t, i) => <li key={i}>{t}</li>)}</ul>
          </details>
        )}
        {d.rewards.length > 0 && (
          <details open>
            <summary className="cursor-pointer text-xs text-muted">Reward history</summary>
            <div className="mt-2 space-y-1 text-xs">
              {d.rewards.map((r) => (
                <div key={r.id} className="flex justify-between rounded border border-border px-2.5 py-1.5">
                  <span>{r.kind === "gpu" ? "Training contribution" : "Referral payment"} · {formatNumber(r.amount, 1)} tokens
                    {r.status === "pending" && <span className="text-faint"> · available {new Date(r.available_at * 1000).toLocaleDateString()}</span>}
                    {r.reason && r.status !== "pending" && <span className="text-faint"> · {r.reason}</span>}
                  </span>
                  <Badge variant={tone[r.status]}>{r.status}</Badge>
                </div>
              ))}
            </div>
          </details>
        )}
      </CardContent>
    </Card>
  );
}
