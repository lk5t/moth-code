import { serverApi,useAccount } from "@/lib/account";
import { useResource } from "@/lib/hooks";
import { Card,CardContent,CardHeader,CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
const load=(path:string)=>serverApi<any>(path);
export function GrowthDiagnostics(){
 const server=useAccount(s=>s.serverUrl),token=useAccount(s=>s.token);
 const {data,error,reload}=useResource<any>('/v1/admin/evolution/growth-diagnostics',[],undefined,server+'\0'+token,load);
 return <Card><CardHeader><CardTitle>Why has model size stayed the same?</CardTitle></CardHeader><CardContent className="space-y-2 text-xs">
  {error && <p role="alert">Growth evidence unavailable: {error}</p>}
  {data && <><p>{data.explanation}</p><p>Growth planning: {data.enabled?'enabled':'disabled'} · registered parameters: {data.registered_params?.toLocaleString()??'unavailable'} · architecture count: {data.architecture_params?.toLocaleString()??'unavailable'}</p>
   {data.blockers?.map((reason:string)=><p key={reason} className="text-warning">{reason}</p>)}
   {data.decision?.grow && <p>Evidence supports a candidate of {data.decision.params_after.toLocaleString()} parameters. {data.decision.requires_approval?'Owner expansion approval is required.':'The configured approval threshold permits proposing it.'} This is a proposal, not a deployed expansion.</p>}
   <p>{data.compatibility}</p><p className="text-muted">{data.scope}</p>
   <details><summary>Evidence, limits and previous attempts</summary><pre className="max-h-64 overflow-auto whitespace-pre-wrap">{JSON.stringify({evidence:data.evidence,budget:data.budget,estimated_training_bytes:data.estimated_training_bytes,available_backend:data.available_backend,attempts:data.attempts},null,2)}</pre></details>
  </>}
  <Button size="sm" variant="secondary" onClick={()=>void reload()}>Refresh growth evidence</Button>
 </CardContent></Card>;
}
