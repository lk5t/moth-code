import {useEffect,useRef,useState} from 'react';
import {serverApi,useAccount} from '@/lib/account';
import {useResource} from '@/lib/hooks';
import type {ActivityEvent} from '@/lib/activity-notices';
import {timeAgo} from '@/lib/utils';
type Feed={events:ActivityEvent[];next_cursor:string|null;generation:number};
const loader=(path:string)=>serverApi<Feed>(path);
export function CloudActivity(){
 const token=useAccount(s=>s.token),server=useAccount(s=>s.serverUrl);
 const [category,setCategory]=useState('all');
 const [older,setOlder]=useState<Feed|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const {data,error:loadError,reload}=useResource<Feed>(token?'/v1/intelligence/activity?category='+category:null,[],undefined,server+'\0'+token,loader);
 const identity=server+'\0'+token+'\0'+category+'\0'+data?.generation;
 const current=useRef(identity);current.current=identity;
 useEffect(()=>{setOlder(null);setError('');setBusy(false);},[identity]);
 useEffect(()=>{const timer=setInterval(()=>{if(!document.hidden)void reload();},15000);return()=>clearInterval(timer);},[reload]);
 if(!token)return <p className="text-sm text-muted">Sign in to see recorded Cloud activity.</p>;
 const extra=older?.generation===data?.generation?older:null;
 const events=[...(data?.events||[]),...(extra?.events||[])].filter((event,index,all)=>all.findIndex(other=>other.id===event.id)===index).slice(0,500);
 const cursor=extra?.next_cursor ?? (!extra?data?.next_cursor:null);
 const more=async()=>{if(!cursor||busy)return;const started=current.current;setBusy(true);try{const page=await loader('/v1/intelligence/activity?category='+category+'&cursor='+encodeURIComponent(cursor));if(started===current.current)setOlder({generation:page.generation,next_cursor:page.next_cursor,events:[...(extra?.events||[]),...page.events]});}catch(e){if(started===current.current)setError((e as Error).message);}finally{if(started===current.current)setBusy(false);}};
 return <section className="space-y-3" aria-label="Cloud activity">
  <label className="text-xs">Activity filter<select value={category} onChange={e=>setCategory(e.target.value)} className="ml-2 rounded border border-border p-1">{['all','training','data','network','deployment','update','error','administration'].map(value=><option key={value}>{value}</option>)}</select></label>
  <button className="ml-3 text-xs" onClick={()=>void reload()}>Refresh activity</button>
  {(loadError||error)&&<p role="alert">{loadError||error}</p>}
  {!data&&!loadError&&<p role="status">Loading recorded activity…</p>}
  {data&&!events.length&&<p className="text-xs text-muted">No events in this category.</p>}
  <ol className="stagger space-y-2">{events.map(event=><li key={event.id} className="lift rounded border border-border p-2 text-xs"><p>{event.message}</p><p className="text-muted">{event.category} · {event.level} · {timeAgo(event.ts)}</p></li>)}</ol>
  {cursor&&events.length<500&&<button disabled={busy} onClick={()=>void more()}>{busy?'Loading…':'Load older activity'}</button>}
 </section>;
}
