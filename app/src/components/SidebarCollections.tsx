import { useEffect,useState } from "react";
import { FolderOpen, Plus, Search } from "lucide-react";
import { ConversationList } from "./ConversationList";
import { appStore,useApp } from "@/lib/app-state";
import { useAccount } from "@/lib/account";
import { useResource } from "@/lib/hooks";
import { useEvent } from "@/lib/events";
import { navigate } from "@/lib/navigation";
import { openProjectPath,pickProject } from "@/features/workspace/project-actions";

export function requestChat(conversationId:number|null,title?:string){
 if(appStore.getState().chatSession.busy)return;
 appStore.setState(s=>({view:'chat',chatRequest:{sequence:(s.chatRequest?.sequence??0)+1,conversationId,title}}));
}
export function SidebarCollections(){
 const projects=useApp(s=>s.projects);
 const token=useAccount(s=>s.token),server=useAccount(s=>s.serverUrl);
 const [query,setQuery]=useState(''),[search,setSearch]=useState('');
 const [opening,setOpening]=useState(false),[error,setError]=useState<string|null>(null);
 useEffect(()=>{const timer=setTimeout(()=>setSearch(query),200);return()=>clearTimeout(timer);},[query]);
 const {data:chats,error:loadError,reload}=useResource<{id:number;title:string}[]>(`/api/conversations?scope=general&q=${encodeURIComponent(search)}`,[],undefined,server+'\0'+token);
 useEvent('chat',e=>{if(e.kind==='done'||e.kind==='error')void reload();});
 useEvent('conversations',()=>void reload());
 const open=async(path?:string)=>{
  setOpening(true);setError(null);
  try{if(path)await openProjectPath(path);else await pickProject();}
  catch(e){setError((e as Error).message);}finally{setOpening(false);}
 };
 const recent=[...projects].sort((a,b)=>b.last_opened-a.last_opened).slice(0,4);
 return <div className="flex min-h-0 flex-1 flex-col gap-3 text-xs">
  <label className="flex shrink-0 items-center gap-2 rounded-md border border-border bg-surface px-2"><Search className="size-3.5 text-faint"/><input aria-label="Search conversations" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search chats" className="h-8 min-w-0 flex-1 bg-transparent text-xs outline-none"/></label>
  <div className="min-h-0 flex-1 space-y-4 overflow-y-auto">
   <div>
    <ConversationList chats={chats??[]} searching={!!search} reload={()=>void reload()}/>
    {!chats?.length&&!loadError&&<p className="px-2 py-1 text-faint">{search?'No matching conversations.':'Start a new chat with MOTH.'}</p>}
    {loadError&&<p role="alert" className="px-2 text-danger">Chat history unavailable. <button onClick={()=>void reload()} className="underline">Retry</button></p>}
   </div>
   <section aria-label="Recent projects"><div className="mb-1 flex items-center justify-between"><h2 className="text-[10px] uppercase tracking-wider text-faint">Projects</h2><button aria-label="Open project" title="Open project" disabled={opening} onClick={()=>void open()} className="rounded p-1 text-muted hover:text-fg"><Plus className="size-3.5"/></button></div>
    {recent.map(project=><button key={project.id} disabled={opening} title={project.path} onClick={()=>void open(project.path)} className="flex h-8 w-full items-center gap-2 rounded px-2 text-left text-muted hover:bg-surface-2 hover:text-fg disabled:opacity-50"><FolderOpen className="size-3 shrink-0"/><span className="truncate">{project.name}</span></button>)}
    {!recent.length&&<p className="px-2 py-1 text-faint">Open a project when you need coding tools.</p>}
    <button className="mt-1 px-2 text-[11px] text-muted hover:text-fg" onClick={()=>navigate('workspace')}>All projects and coding tools</button>
    {error&&<p role="alert" className="px-2 text-danger">{error}</p>}
   </section>
  </div>
 </div>;
}
