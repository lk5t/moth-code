import { createStore } from "./store";
import { subscribe, type MothEvent } from "./events";
import { get } from "./backend";

export type Pulse = "idle" | "thinking" | "generating" | "training" | "evaluating" | "deploying" | "error" | "offline";
const initial = { local: [] as Pulse[], cloud: [] as Pulse[], connected: null as boolean | null, error: false };
export const livingActivity = createStore(initial);
const requests = new Map<string, "thinking" | "generating">();
const jobs = new Map<string, Pulse>();
let started = false;
let revision=0;
function publish() { livingActivity.setState({local: [...new Set([...requests.values(), ...jobs.values()])]}); }
export function clearLocalActivity() { revision++; requests.clear(); jobs.clear(); livingActivity.setState({...initial,local:[],cloud:[]}); }
export function setCloudActivity(cloud: Pulse[]) { livingActivity.setState({cloud}); }
export function markActivityError() { livingActivity.setState({error:true}); }
export function dismissActivityError() { livingActivity.setState({error:false}); }
function jobActivity(job: Record<string, any>) {
  if (!job.id) return;
  if (job.status === "running") {
    const kind = job.kind;
    if (["train", "community"].includes(kind)) jobs.set(job.id,"training");
    else if (["evaluate", "evaluation"].includes(kind)) jobs.set(job.id,"evaluating");
    else if (kind === "publish") jobs.set(job.id,"deploying");
  } else {
    jobs.delete(job.id);
    if (job.status === "failed") markActivityError();
  }
  publish();
}
export function observeActivity(event: MothEvent) {
  if(event.topic === "connection" || event.topic === "job") revision++;
  if (event.topic === "connection") {
    livingActivity.setState({connected:!!event.connected});
    if (!event.connected) {requests.clear();jobs.clear();publish();}
    else {const captured=revision; get<Record<string,any>[]>("/api/jobs").then((all) => {if(captured===revision)all.forEach(jobActivity);}).catch(() => {});}
  }
  if (event.topic === "job" && event.job) jobActivity(event.job);
  if (event.topic !== "chat") return;
  const key = event.message_key ?? event.conversation_id;
  if (key == null) return;
  if (event.kind === "start") {requests.set(String(key),"thinking");dismissActivityError();}
  if (event.kind === "token" || event.kind === "replace") requests.set(String(key),"generating");
  if (event.kind === "done" || event.kind === "error") requests.delete(String(key));
  if (event.kind === "error") markActivityError();
  publish();
}
export function startLivingActivity() { if (!started) {started=true;subscribe("*",observeActivity);} }
export function pulses(state: typeof initial): Pulse[] {
  const states = new Set<Pulse>([...state.local,...state.cloud]);
  if(state.error) states.add("error");
  if(state.connected === false) states.add("offline");
  const ordered: Pulse[] = ["generating","thinking","training","evaluating","deploying","error","offline"];
  const result = ordered.filter((s) => states.has(s));
  return result.length ? result : ["idle"];
}
