/**
 * Owner Dashboard → Intelligence: the dataset library, feedback review, weaknesses and curriculum,
 * and the (optional, off by default) external provider. Every number comes from MOTH Cloud.
 */
import { useState } from "react";
import { BookOpen, Brain, Check, Database, Download, RefreshCw, Target, ThumbsDown, X } from "lucide-react";
import { serverApi } from "@/lib/account";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input, Textarea } from "@/components/ui/input";
import { EmptyState } from "@/components/ui/empty";
import { formatNumber, timeAgo } from "@/lib/utils";
import { formatBytes, useAction, usePoll } from "./ops";

type Any = Record<string, any>;
const post = (path: string, json?: unknown) => serverApi(path, { method: "POST", json });
const pct = (x?: number | null) => (x == null ? "—" : `${(x * 100).toFixed(1)}%`);

export function IntelligencePanel() {
  const [tab, setTab] = useState<"library" | "feedback" | "weak" | "knowledge">("library");
  const tabs: [typeof tab, string][] = [["library", "Dataset library"], ["weak", "Weaknesses & curriculum"],
    ["feedback", "Feedback"], ["knowledge", "Shared knowledge"]];
  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-1">
        {tabs.map(([k, l]) => (
          <Button key={k} size="sm" variant={tab === k ? "default" : "ghost"} onClick={() => setTab(k)}>{l}</Button>
        ))}
      </div>
      {tab === "library" && <Library />}
      {tab === "weak" && <Weaknesses />}
      {tab === "feedback" && <Feedback />}
      {tab === "knowledge" && <SharedKnowledge />}
    </div>
  );
}

function Library() {
  const { data, load } = usePoll<Any>("/v1/admin/library", 5000);
  const { run, view } = useAction(load);
  if (!data) return null;
  const building = data.builds.find((b: Any) => b.status === "queued" || b.status === "running");
  const updates: Any[] = data.updates?.results ?? [];
  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Database className="size-4 text-accent" />Approved datasets</CardTitle>
          <CardDescription>Each dataset is pinned to an exact version and checked against its SHA-256 before use. Files download once and are reused.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2 text-xs">
          {data.datasets.map((d: Any) => {
            const upd = updates.find((u) => u.id === d.id && u.update_available);
            return (
              <div key={d.id} className="flex flex-wrap items-center gap-2 border-b border-border pb-2 last:border-0">
                <span className="min-w-48 text-fg">{d.name}</span>
                <Badge>{d.domain}</Badge>
                <a className="text-accent hover:underline" href={d.license_url} target="_blank" rel="noreferrer">{d.license}</a>
                <span className="text-muted">{d.download_bytes ? formatBytes(d.download_bytes) : "no download"}</span>
                <Badge variant={d.downloaded ? "success" : "default"}>{d.downloaded ? "verified" : "not downloaded"}</Badge>
                {d.revision && <span className="font-mono text-faint">{d.revision.slice(0, 10)}</span>}
                {upd && (
                  <Button size="sm" variant="secondary" onClick={() => run(() => post("/v1/admin/library/approve-update",
                    { dataset: d.id, revision: upd.latest }), `${d.name} will use the new version in the next build.`)}>
                    Approve update {upd.latest.slice(0, 8)}</Button>
                )}
              </div>
            );
          })}
          <div className="flex flex-wrap gap-2 pt-1">
            <Button size="sm" disabled={!!building} onClick={() => run(() => post("/v1/admin/library/build", {}),
              "Building the training corpus in the background.")}><Download />{building ? "Building…" : "Download & build corpus"}</Button>
            <Button size="sm" variant="secondary" onClick={() => run(() => post("/v1/admin/library/check-updates"),
              "Checked upstream versions.")}><RefreshCw />Check for dataset updates</Button>
          </div>
          {view}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Corpus builds</CardTitle>
          <CardDescription>Cleaned, filtered, deduplicated and decontaminated (no overlap with the benchmarks). Each domain becomes an approved training dataset.</CardDescription></CardHeader>
        <CardContent className="flex flex-col gap-3 text-xs">
          {!data.builds.length && <div className="text-muted">No build yet.</div>}
          {data.builds.map((b: Any) => (
            <div key={b.id} className="flex flex-col gap-1 border-b border-border pb-2 last:border-0">
              <div className="flex items-center gap-2">
                <span className="text-fg">Build {b.id}</span>
                <Badge variant={b.status === "ready" ? "success" : b.status === "failed" ? "danger" : "accent"}>{b.status}</Badge>
                <span className="text-muted">{timeAgo(b.created_at)}</span>
                {b.content_sha256 && <span className="font-mono text-faint">{b.content_sha256.slice(0, 12)}</span>}
              </div>
              {b.error && <div className="text-danger">{b.error}</div>}
              {b.domains && (
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-muted">
                  {Object.entries(b.domains as Record<string, Any>).map(([d, v]) => (
                    <span key={d}>{d}: {formatNumber(v.records)} records · {formatBytes(v.chars)} text</span>
                  ))}
                </div>
              )}
              {b.sources && (
                <div className="flex flex-wrap gap-x-4 text-faint">
                  {b.sources.map((s: Any) => s.stats && (
                    <span key={s.id}>{s.id}: kept {formatNumber(s.stats.kept)}/{formatNumber(s.stats.read)}
                      {s.stats.duplicate || s.stats.near_duplicate ? ` · ${formatNumber((s.stats.duplicate ?? 0) + (s.stats.near_duplicate ?? 0))} duplicates` : ""}
                      {s.stats.eval_overlap ? ` · ${s.stats.eval_overlap} benchmark overlaps removed` : ""}</span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </CardContent>
      </Card>
    </>
  );
}

function Weaknesses() {
  const { data: w } = usePoll<Any>("/v1/intelligence/weaknesses", 30000);
  const { data: c } = usePoll<Any>("/v1/intelligence/curriculum", 30000);
  if (!w || !c) return null;
  if (w.version == null) return <EmptyState title="No deployed model yet">Weaknesses are measured on the deployed model's benchmark results.</EmptyState>;
  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Target className="size-4 text-accent" />Measured weaknesses (model v{w.version})</CardTitle>
          <CardDescription>From held-out benchmarks that are never trained on{w.parent ? `, compared with v${w.parent}` : ""}, plus recurring problems users report.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-1.5 text-xs">
          {w.ranked.map((r: Any) => (
            <div key={r.capability} className="flex flex-wrap items-center gap-2">
              <span className="w-28 text-fg">{r.capability}</span>
              <span className="w-32 text-muted">{r.metric}: {r.higher_is_better ? pct(r.value) : r.value?.toFixed?.(3)}</span>
              {r.target != null && <span className="text-faint">target {pct(r.target)}</span>}
              {r.regression && <Badge variant="danger">regressed</Badge>}
              {r.feedback_negative_rate != null && <Badge variant="warning">{pct(r.feedback_negative_rate)} negative feedback</Badge>}
              <span className="ml-auto text-faint">weakness {(r.weakness * 100).toFixed(0)}</span>
            </div>
          ))}
          {!!w.not_measured.length && <div className="text-faint">Not measured yet: {w.not_measured.join(", ")}.</div>}
          {w.recommendations.map((r: Any) => <div key={r.capability} className="text-muted">→ {r.action}. {r.reason}</div>)}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Brain className="size-4 text-accent" />Learning curriculum</CardTitle>
          <CardDescription>Stage: <b>{c.progress.stage}</b> · {formatNumber(c.progress.stage_tokens)} tokens trained in this stage
            {c.progress.stage_budget ? ` of ${formatNumber(c.progress.stage_budget)}` : ""}.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-1 text-xs">
          <div className="text-muted">Next training mixture{c.next_mixture.note ? ` — ${c.next_mixture.note}` : ""}:</div>
          {Object.entries((c.next_mixture.weights ?? {}) as Record<string, number>).map(([d, v]) => (
            <div key={d} className="flex items-center gap-2">
              <span className="w-28">{d}</span>
              <div className="h-1.5 flex-1 rounded bg-surface-2"><div className="h-1.5 rounded bg-accent" style={{ width: `${v * 100}%` }} /></div>
              <span className="w-24 text-right text-faint">{pct(v)} · {c.next_mixture.expected_epochs?.[d]}× data</span>
            </div>
          ))}
        </CardContent>
      </Card>
    </>
  );
}

function Feedback() {
  const { data, load } = usePoll<Any>("/v1/admin/feedback", 15000);
  const { run, view } = useAction(load);
  if (!data) return null;
  const caps = Object.entries((data.summary.capabilities ?? {}) as Record<string, Any>);
  return (
    <>
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><ThumbsDown className="size-4 text-accent" />What users report</CardTitle>
          <CardDescription>{data.summary.total} ratings. Conversations are stored only for users who allowed training use.</CardDescription></CardHeader>
        <CardContent className="flex flex-col gap-1 text-xs">
          {caps.length === 0 && <div className="text-muted">No ratings yet.</div>}
          {caps.map(([k, v]) => <div key={k}>{k}: {v.ratings} ratings · {pct(v.negative_rate)} negative</div>)}
          {data.summary.recurring_weaknesses.map((r: Any) => (
            <div key={r.capability} className="text-warning">Recurring problem: {r.capability} ({r.top_problem ?? "various"})</div>
          ))}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Review</CardTitle><CardDescription>Approved items with consent become training data in the next corpus build.</CardDescription></CardHeader>
        <CardContent className="flex flex-col gap-2 text-xs">
          {data.feedback.filter((f: Any) => f.consent && f.status === "new").slice(0, 30).map((f: Any) => (
            <div key={f.id} className="flex flex-col gap-1 border-b border-border pb-2">
              <div className="flex items-center gap-2"><Badge variant={f.rating > 0 ? "success" : "danger"}>{f.rating > 0 ? "good" : f.category || "bad"}</Badge>
                <span className="text-faint">{f.capability} · {timeAgo(f.created_at)}</span></div>
              <div className="text-muted"><b>Prompt:</b> {f.prompt}</div>
              <div className="text-muted"><b>Answer:</b> {f.response}</div>
              {f.correction && <div className="text-success"><b>Correction:</b> {f.correction}</div>}
              <div className="flex gap-2">
                <Button size="sm" onClick={() => run(() => post(`/v1/admin/feedback/${f.id}/review`, { approve: true }), "Approved.")}><Check />Use for training</Button>
                <Button size="sm" variant="ghost" onClick={() => run(() => post(`/v1/admin/feedback/${f.id}/review`, { approve: false }), "Rejected.")}><X />Reject</Button>
              </div>
            </div>
          ))}
          {!data.feedback.some((f: Any) => f.consent && f.status === "new") && <div className="text-muted">Nothing to review.</div>}
          {view}
        </CardContent>
      </Card>
    </>
  );
}

function SharedKnowledge() {
  const { data, load } = usePoll<Any>("/v1/knowledge", 30000);
  const { run, view } = useAction(load);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [source, setSource] = useState("");
  const shared = (data?.documents ?? []).filter((d: Any) => d.shared);
  return (
    <Card>
      <CardHeader><CardTitle className="flex items-center gap-2"><BookOpen className="size-4 text-accent" />Shared knowledge</CardTitle>
        <CardDescription>Approved documents every user's answers may cite. Adding a document with the same source creates a new version.</CardDescription></CardHeader>
      <CardContent className="flex flex-col gap-2 text-xs">
        <Input placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
        <Input placeholder="Source (URL or file name)" value={source} onChange={(e) => setSource(e.target.value)} />
        <Textarea rows={4} placeholder="Text" value={text} onChange={(e) => setText(e.target.value)} />
        <div><Button size="sm" disabled={!title || !text} onClick={() => run(async () => {
          await post("/v1/admin/knowledge", { title, text, source }); setTitle(""); setText(""); setSource("");
        }, "Added.")}>Add shared document</Button></div>
        {view}
        {shared.map((d: Any) => (
          <div key={d.id} className="flex items-center justify-between border-t border-border pt-1.5">
            <span>{d.title} <span className="text-faint">v{d.version} · {formatBytes(d.chars)}</span></span>
            <Button size="sm" variant="ghost" onClick={() => run(() => serverApi(`/v1/knowledge/${d.id}`, { method: "DELETE" }), "Removed.")}><X /></Button>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
