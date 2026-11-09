import { useEffect } from "react";
import { serverApi, useAccount } from "./account";
import { createStore } from "./store";
import { setCloudActivity, type Pulse } from "./living-activity";

type Snapshot = Record<string, any>;
const empty = { data: null as Snapshot | null, error: null as string | null, updatedAt: null as number | null, loading: false };
const snapshots = createStore(empty);
const consumers = new Map<symbol,string>();
let scope = "", epoch = 0, owner = false, timer: ReturnType<typeof setTimeout> | null = null;
let request: AbortController | null = null, pendingEpoch = -1;
let listeners = false;
function stop() {if(timer) clearTimeout(timer);timer=null;request?.abort();request=null;}
function cloudStages(data: Snapshot): Pulse[] {
  const training=data.training;
  if(training?.paused) return [];
  const status=training?.cycle?.status;
  if(status === "training" && training.experiments?.some((e:Snapshot) => e.status === "running")) return ["training"];
  if(status === "evaluating") return ["evaluating"];
  if(status === "deploying") return ["deploying"];
  return [];
}
async function load() {
  if(!scope || document.hidden || pendingEpoch === epoch) return;
  const captured=epoch, controller=new AbortController();
  request=controller;pendingEpoch=captured;
  const timeout=setTimeout(() => controller.abort(),15000);
  if(!snapshots.getState().data) snapshots.setState({loading:true});
  try {
    const data=await serverApi<Snapshot>("/v1/intelligence/progress",{signal:controller.signal});
    if(captured !== epoch) return;
    snapshots.setState({data,error:null,updatedAt:Date.now(),loading:false});setCloudActivity(cloudStages(data));
  } catch(error) {
    if(captured !== epoch) return;
    snapshots.setState({data:null,error:controller.signal.aborted ? "The status request timed out. Check the connection and retry." : (error as Error).message,updatedAt:null,loading:false});
    setCloudActivity(["offline"]);
  } finally {
    clearTimeout(timeout);
    if(request === controller) request=null;
    if(pendingEpoch === captured) pendingEpoch=-1;
    if(captured === epoch && scope && !document.hidden) timer=setTimeout(load,owner ? 5000 : 20000);
  }
}
function visible() {if(timer) clearTimeout(timer);timer=null;if(!document.hidden) void load();}
export function refreshCloudProgress(discard = false) {
  if(timer) clearTimeout(timer);timer=null;
  if(discard) {epoch++;request?.abort();request=null;snapshots.setState({...empty,loading:!!scope});setCloudActivity([]);}
  void load();
}
function acquire(key: string, isOwner: boolean) {
  const id=Symbol();consumers.set(id,key);
  if(!listeners) {document.addEventListener("visibilitychange",visible);window.addEventListener("online",visible);listeners=true;}
  if(scope !== key) {epoch++;stop();scope=key;owner=isOwner;snapshots.setState({...empty,loading:!!key});setCloudActivity([]);if(key) void load();}
  return () => {
    consumers.delete(id);
    if(![...consumers.values()].includes(scope)) {epoch++;stop();scope="";snapshots.setState({...empty});setCloudActivity([]);}
    if(!consumers.size && listeners) {document.removeEventListener("visibilitychange",visible);window.removeEventListener("online",visible);listeners=false;}
  };
}
/** One request loop shared by Overview, Chat, Code, navigation and history, scoped to the current account. */
export function useCloudProgress() {
  const token=useAccount((s) => s.token), server=useAccount((s) => s.serverUrl), isOwner=useAccount((s) => s.user?.role === "owner");
  const key=token ? `${server ?? ""}\0${token}\0${isOwner}` : "";
  const snapshot=snapshots.useStore((s) => s);
  useEffect(() => acquire(key,isOwner),[key,isOwner]);
  // Do not expose a previous account's snapshot even for the render before effect cleanup.
  return scope === key ? snapshot : {...empty,loading:!!key};
}
