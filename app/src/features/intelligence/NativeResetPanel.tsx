import { useEffect, useRef, useState } from "react";
import { serverApi, useAccount } from "@/lib/account";
import { useResource } from "@/lib/hooks";
import { refreshCloudProgress } from "@/lib/cloud-progress";
import { secure, formatBytes } from "@/features/owner/ops";
import { navigate } from "@/lib/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Plan=Record<string,any>;
const path='/v1/admin/evolution/native-reset';
const load=(url:string)=>serverApi<Plan>(url);
const confirmationText='DELETE ALL NATIVE AI DATA';
const backupText='DELETE MANAGED AI BACKUPS';
export function NativeResetPanel(){
 const owner=useAccount(s=>s.user?.role==='owner'), token=useAccount(s=>s.token), server=useAccount(s=>s.serverUrl);
 const {data:plan,error,reload}=useResource<Plan>(owner?path:null,[],undefined,server+'\0'+token,load);
 const [backups,setBackups]=useState(false),[confirmation,setConfirmation]=useState(''),[backupConfirmation,setBackupConfirmation]=useState('');
 const current=useRef({server,token});current.current={server,token};
 useEffect(()=>{setConfirmation('');setBackupConfirmation('');setBackups(false);setNotice('');},[server,token]);
 const [busy,setBusy]=useState(false),[notice,setNotice]=useState('');
 if(!owner)return null;
 const act=async(suffix:string,json:unknown)=>{setBusy(true);setNotice('');try{await secure(()=>{if(current.current.server!==server || current.current.token!==token)throw new Error("Account changed; inspect the current deployment before continuing.");return serverApi(path+suffix,{server,token,method:'POST',json,timeoutMs:60000});});setConfirmation('');setBackupConfirmation('');refreshCloudProgress(true);await reload();}catch(e){setNotice((e as Error).message);await reload();}finally{setBusy(false);}};
 const pending=['fencing','deleting','failed'].includes(plan?.status);
 return <section className="space-y-3 rounded-lg border border-danger/50 p-3 text-xs" aria-label="Delete all native AI data">
  <h3 className="font-semibold text-danger">Genesis Reset — Delete All Native AI Data</h3>
  <p>Owner-only destructive operation for <strong>{server}</strong>. Deletes deployment-owned models, tokenizers, checkpoints, datasets, experiments, evaluations and native history. Stops native serving and training. It creates no replacement model.</p>
  <p>Accounts, authentication, billing, ordinary Chat, projects, application settings, worker consent, signing keys and installed software are preserved. This is separate from deleting one selected model.</p>
  <p>Cloud reset cannot erase exported packages, infrastructure snapshots, other deployments or offline Desktop/Worker copies. Known retained copies and unacknowledged workers are reported after execution.</p>
  {!pending && <><label className="flex items-center gap-2"><input type="checkbox" checked={backups} onChange={e=>setBackups(e.target.checked)} disabled={busy}/>Include managed GENESIS model backups (separate confirmation required)</label>
   <Button size="sm" variant="secondary" disabled={busy} onClick={()=>void act('/preview',{include_managed_backups:backups})}>Inspect deletion inventory</Button></>}
  {plan?.inventory && <div><p className="font-medium">Deletion inventory · expires 10 minutes after preview</p>
   {plan.inventory.roots.map((r:Plan)=><p key={r.category}>{r.category}: {r.files} files · {formatBytes(r.bytes)}</p>)}
   <details><summary>Database records and preserved copies</summary>{Object.entries(plan.inventory.records).map(([name,count])=><p key={name}>{name}: {String(count)}</p>)}<p>Managed backup files: {plan.inventory.managed_backup_files} · {plan.backups?'included':'retained'}</p>{plan.inventory.external_references.map((ref:string)=><p key={ref}>External original retained: {ref}</p>)}</details>
   <p>{plan.inventory.disclosure}</p></div>}
  {plan && (plan.status==='preview'||pending) && <>
   <label>Type {confirmationText}<Input aria-label="Confirm all native AI deletion" value={confirmation} onChange={e=>setConfirmation(e.target.value)} autoComplete="off"/></label>
   {plan.backups && <label>Separately type {backupText}<Input aria-label="Confirm managed AI backup deletion" value={backupConfirmation} onChange={e=>setBackupConfirmation(e.target.value)} autoComplete="off"/></label>}
   <Button size="sm" disabled={busy || confirmation!==confirmationText || (plan.backups && backupConfirmation!==backupText)} onClick={()=>void act('/execute',{reset_id:plan.id,confirmation,backup_confirmation:backupConfirmation})}>{busy?'Reset operation running…':pending?'Retry fenced reset recovery':'Permanently delete reviewed native AI data'}</Button>
  </>}
  {plan?.status==='completed' && <div><p>Deployment-owned native AI data verified empty. No replacement model was created.</p><p>Retained managed backup files: {plan.retained_managed_backup_files} · External originals: {plan.retained_external_copies}</p><p>Workers awaiting cleanup acknowledgement: {plan.pending_worker_acknowledgements?.length || 0}</p><p>Reported unverified/other-scope worker cache files retained: {Object.values(plan.reported_retained_worker_cache_files || {}).reduce((sum:number,n)=>sum+Number(n),0)}</p><p>{plan.disclosure}</p>
    <Button size="sm" variant="secondary" onClick={()=>navigate('data')}>Prepare a tokenizer and dataset</Button><Button size="sm" variant="ghost" onClick={()=>navigate('intelligence')}>Open native training setup</Button><button onClick={()=>void reload()}>Refresh worker acknowledgements</button></div>}
  {(error||notice||plan?.error) && <p role="alert" className="text-danger">{notice||error||plan?.error}</p>}
 </section>;
}
