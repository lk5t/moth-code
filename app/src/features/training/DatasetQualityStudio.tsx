import { useState } from "react";
import { get, post } from "@/lib/backend";
import { Button } from "@/components/ui/button";
import { SourcePicker, type SourceSel } from "./SourcePicker";

type Report = {status: string; records: number; training_tokens: number; duplicates: number; near_duplicates: number; validation_overlap: number; repetition_warnings: number; secrets?: number; truncated: boolean; tokenizer_fingerprint: string; sources: {source: string; license: string; format: string; bytes: number | null}[]; token_lengths: {min: number; max: number; mean: number}; issues: {source: string; record: number; message: string}[]; preview: {source: string; record: string; text: string; tokens: number}[]; cleaning_preview: {retained: number; removed: number; policy: string}; limitations: string[]};
export function DatasetQualityStudio({tokenizers, datasets = []}: {tokenizers: {name: string; fingerprint: string}[]; datasets?: {name: string}[]}) {
  const [prepared,setPrepared]=useState<Record<string, any>|null>(null);
  const [dataset,setDataset]=useState('');
  const [sources,setSources]=useState<SourceSel[]>([]), [validation,setValidation]=useState<SourceSel[]>([]);
  const [selected,setSelected]=useState(''), [report,setReport]=useState<Report|null>(null);
  const [text,setText]=useState(''), [tokens,setTokens]=useState<{ids:number[];count:number;decoded:string;fingerprint:string}|null>(null);
  const [error,setError]=useState(''), [busy,setBusy]=useState(false);
  const tokenizer=selected || tokenizers[0]?.name || '';
  async function run(preview=false) {
    setBusy(true);setError('');setReport(null);setTokens(null);
    try {if(preview) setTokens(await post('/api/tokenizers/preview',{tokenizer,text}));
      else setReport(await post('/api/datasets/quality',{tokenizer,sources,validation_sources:validation}));
    } catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  const sel = "rounded-md border border-border bg-bg px-2 py-1 text-xs text-fg";
  const sum = "cursor-pointer text-muted hover:text-fg";
  return <section className="space-y-3 rounded-xl border border-border bg-surface p-4 text-xs" aria-label="Dataset quality studio">
    <div><h2 className="text-sm font-semibold">Dataset Quality Studio</h2>
      <p className="mt-1 text-muted">Inspect sources before preparation. Preview does not alter files or approve data for training. Large sources are sampled.</p></div>
    {tokenizers.length === 0 ? <p className="rounded-lg border border-border p-3 text-muted">Create a tokenizer first (step 1 above): token counts are only real when measured with the tokenizer the model will use.</p> :
      <label className="flex flex-wrap items-center gap-2 text-muted">Inspection tokenizer<select className={sel} value={tokenizer} onChange={e=>{setSelected(e.target.value);setReport(null);setTokens(null);}}>{tokenizers.map(t=><option key={t.name} value={t.name}>{t.name}</option>)}</select></label>}
    <SourcePicker value={sources} onChange={value=>{setSources(value);setReport(null);}}/>
    <details><summary className={sum}>Advanced: validation sources for overlap checks</summary><p className="my-2 text-muted">Select independent held-out sources. No selected source means overlap is untested.</p><SourcePicker value={validation} onChange={value=>{setValidation(value);setReport(null);}}/></details>
    <Button size="sm" disabled={busy || !tokenizer || !sources.length} onClick={()=>void run()}>Inspect quality and cleaning preview</Button>
    {busy && <p role="status" className="text-muted">Inspecting source data…</p>}{error && <p role="alert" className="text-danger">{error}</p>}
    {report && <div className="space-y-2 rounded-lg border border-border p-3">
      <p className="text-sm text-fg">{report.records} examples · {report.training_tokens.toLocaleString()} estimated training tokens · {report.status.replaceAll('_',' ')}</p>
      <p>Exact duplicates: {report.duplicates} · Potential near duplicates: {report.near_duplicates} · Repetition warnings: {report.repetition_warnings}</p>
      {(report.secrets ?? 0) > 0 && <p className="text-warning">Possible credentials in {report.secrets} {report.secrets === 1 ? "example" : "examples"} — they are replaced with placeholders before training.</p>}
      <p>Validation overlap: {validation.length ? report.validation_overlap : 'Not tested — choose validation sources'}</p>
      <p>Token length: {report.token_lengths.min}–{report.token_lengths.max} (mean {report.token_lengths.mean})</p>
      {report.truncated && <p className="text-warning">Inspection limit reached; remaining records were not checked.</p>}
      {report.issues.length > 0 && <p className="text-warning">{report.issues.length} import {report.issues.length === 1 ? "problem" : "problems"} found — see diagnostics below.</p>}
      <details><summary className={sum}>Provenance and compatibility</summary><p>Selected tokenizer: {report.tokenizer_fingerprint}</p>{report.sources.map((s,i)=><p key={i}>{s.source} · {s.license} · {s.format}{s.bytes!==null ? ` · ${s.bytes} bytes`:''}</p>)}<p className="text-muted">Prepared dataset fingerprints must match the training model. Token estimates do not approve compatibility with a different model.</p></details>
      <details open={report.issues.length > 0}><summary className={sum}>Import diagnostics and examples</summary>{report.issues.map((i,n)=><p key={n} className="text-warning">{i.source}:{i.record} · {i.message}</p>)}{report.preview.map((p,i)=><pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded bg-bg p-2" key={i}>{p.source}:{p.record} · {p.tokens} tokens{'\n'}{p.text}</pre>)}</details>
      <details><summary className={sum}>Cleaning preview</summary><p>Retain {report.cleaning_preview.retained}; exclude {report.cleaning_preview.removed} valid records.</p><p>{report.cleaning_preview.policy}</p><p className="text-muted">This is a preview. Original sources remain intact.</p></details>
      <details><summary className={sum}>Inspection limits</summary>{report.limitations.map(t=><p key={t}>{t}</p>)}</details>
    </div>}
    {tokenizers.length > 0 && <details><summary className={sum}>Tokenizer preview</summary><label className="mt-2 block text-muted">Sample text<textarea className="mt-1 block w-full rounded-md border border-border bg-bg p-2 text-fg" rows={3} value={text} onChange={e=>{setText(e.target.value);setTokens(null);}} maxLength={4000}/></label>
      <Button size="sm" variant="secondary" className="mt-2" disabled={busy || !tokenizer || !text} onClick={()=>void run(true)}>Preview tokens</Button>
      {tokens && <div className="mt-2 space-y-1"><p>{tokens.count} tokens · {tokens.fingerprint}</p><pre className="max-h-32 overflow-auto whitespace-pre-wrap break-words rounded bg-bg p-2">{tokens.ids.join(', ')}</pre><p>Decoded: {tokens.decoded}</p></div>}
    </details>}
    {datasets.length > 0 && <details><summary className={sum}>Inspect a prepared dataset</summary>
      <div className="mt-2 flex flex-wrap items-center gap-2"><label className="flex items-center gap-2 text-muted">Prepared dataset<select className={sel} value={dataset} onChange={e=>{setDataset(e.target.value);setPrepared(null);}}><option value="">Select a dataset</option>{datasets.map(d=><option key={d.name}>{d.name}</option>)}</select></label>
      <Button size="sm" variant="secondary" disabled={busy || !dataset} onClick={async()=>{setBusy(true);setError('');setPrepared(null);try{setPrepared(await get(`/api/datasets/${encodeURIComponent(dataset)}/quality`));}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}>Check prepared integrity</Button></div>
      {prepared && <div className="mt-2 space-y-1"><p className="text-fg">{prepared.status.replaceAll('_',' ')} · Tokenizer {prepared.tokenizer_available ? 'available' : 'unavailable'}</p><p>Train: {prepared.actual_tokens.train.toLocaleString()} · Validation: {prepared.actual_tokens.val.toLocaleString()} tokens</p><p>Prepared: {new Date(prepared.metadata.created*1000).toLocaleString()}</p><p>Duplicates excluded at preparation: {prepared.metadata.duplicates_skipped || 0}</p>{prepared.metadata.sources.map((s:any,i:number)=><p key={i}>{s.spec} · {s.license}</p>)}{prepared.issues.map((issue:string)=><p key={issue} className="text-warning">{issue}</p>)}<p className="text-muted">{prepared.limitations}</p></div>}
    </details>}
  </section>;
}
