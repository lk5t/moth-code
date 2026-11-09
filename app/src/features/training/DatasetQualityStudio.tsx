import { useState } from "react";
import { get, post } from "@/lib/backend";
import { SourcePicker, type SourceSel } from "./SourcePicker";

type Report = {status: string; records: number; training_tokens: number; duplicates: number; near_duplicates: number; validation_overlap: number; repetition_warnings: number; truncated: boolean; tokenizer_fingerprint: string; sources: {source: string; license: string; format: string; bytes: number | null}[]; token_lengths: {min: number; max: number; mean: number}; issues: {source: string; record: number; message: string}[]; preview: {source: string; record: string; text: string; tokens: number}[]; cleaning_preview: {retained: number; removed: number; policy: string}; limitations: string[]};
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
  return <section className="space-y-3 rounded-lg border border-border p-3 text-xs" aria-label="Dataset quality studio">
    <h2 className="font-medium text-sm">Dataset Quality Studio</h2><p>Inspect sources before preparation. Preview does not alter files or approve data for training. Large sources are sampled.</p>
    {datasets.length > 0 && <details><summary>Inspect a prepared dataset</summary>
      <label>Prepared dataset<select value={dataset} onChange={e=>{setDataset(e.target.value);setPrepared(null);}}><option value="">Select a dataset</option>{datasets.map(d=><option key={d.name}>{d.name}</option>)}</select></label>
      <button disabled={busy || !dataset} onClick={async()=>{setBusy(true);setError('');setPrepared(null);try{setPrepared(await get(`/api/datasets/${encodeURIComponent(dataset)}/quality`));}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}>Check prepared integrity</button>
      {prepared && <div><p>{prepared.status.replaceAll('_',' ')} · Tokenizer {prepared.tokenizer_available ? 'available' : 'unavailable'}</p><p>Train: {prepared.actual_tokens.train} · Validation: {prepared.actual_tokens.val} tokens</p><p>Prepared: {new Date(prepared.metadata.created*1000).toLocaleString()}</p><p>Duplicates excluded at preparation: {prepared.metadata.duplicates_skipped || 0}</p>{prepared.metadata.sources.map((s:any,i:number)=><p key={i}>{s.spec} · {s.license}</p>)}{prepared.issues.map((issue:string)=><p key={issue}>{issue}</p>)}<p>{prepared.limitations}</p></div>}
    </details>}
    <label>Inspection tokenizer<select className="ml-2 border border-border p-1" value={tokenizer} onChange={e=>{setSelected(e.target.value);setReport(null);setTokens(null);}}>{tokenizers.map(t=><option key={t.name} value={t.name}>{t.name}</option>)}</select></label>
    <SourcePicker value={sources} onChange={value=>{setSources(value);setReport(null);}}/>
    <details><summary>Advanced: validation sources for overlap checks</summary><p>Select independent held-out sources. No selected source means overlap is untested.</p><SourcePicker value={validation} onChange={value=>{setValidation(value);setReport(null);}}/></details>
    <button disabled={busy || !tokenizer || !sources.length} onClick={()=>void run()}>Inspect quality and cleaning preview</button>
    {busy && <p role="status">Inspecting source data…</p>}{error && <p role="alert">{error}</p>}
    {report && <div className="space-y-2"><p>{report.records} examples · {report.training_tokens.toLocaleString()} estimated training tokens · {report.status.replaceAll('_',' ')}</p>
      <p>Exact duplicates: {report.duplicates} · Potential near duplicates: {report.near_duplicates} · Repetition warnings: {report.repetition_warnings}</p>
      <p>Validation overlap: {validation.length ? report.validation_overlap : 'Not tested — choose validation sources'}</p>
      <p>Token length: {report.token_lengths.min}–{report.token_lengths.max} (mean {report.token_lengths.mean})</p>
      {report.truncated && <p>Inspection limit reached; remaining records were not checked.</p>}
      <details><summary>Provenance and compatibility</summary><p>Selected tokenizer: {report.tokenizer_fingerprint}</p>{report.sources.map((s,i)=><p key={i}>{s.source} · {s.license} · {s.format}{s.bytes!==null ? ` · ${s.bytes} bytes`:''}</p>)}<p>Prepared dataset fingerprints must match the training model. Token estimates do not approve compatibility with a different model.</p></details>
      <details><summary>Import diagnostics and examples</summary>{report.issues.map((i,n)=><p key={n}>{i.source}:{i.record} · {i.message}</p>)}{report.preview.map((p,i)=><pre className="whitespace-pre-wrap break-words" key={i}>{p.source}:{p.record} · {p.tokens} tokens{'\n'}{p.text}</pre>)}</details>
      <details><summary>Cleaning preview</summary><p>Retain {report.cleaning_preview.retained}; exclude {report.cleaning_preview.removed} valid records.</p><p>{report.cleaning_preview.policy}</p><p>This is a preview. Original sources remain intact.</p></details>
      <details><summary>Inspection limits</summary>{report.limitations.map(t=><p key={t}>{t}</p>)}</details>
    </div>}
    <details><summary>Tokenizer preview</summary><label>Sample text<textarea className="block w-full border border-border p-1" value={text} onChange={e=>{setText(e.target.value);setTokens(null);}} maxLength={4000}/></label><button disabled={busy || !tokenizer || !text} onClick={()=>void run(true)}>Preview tokens</button>
      {tokens && <div><p>{tokens.count} tokens · {tokens.fingerprint}</p><pre className="whitespace-pre-wrap break-words">{tokens.ids.join(', ')}</pre><p>Decoded: {tokens.decoded}</p></div>}
    </details>
  </section>;
}
