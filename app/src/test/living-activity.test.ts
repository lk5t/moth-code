import { beforeEach, expect, it, vi } from "vitest";
vi.mock("@/lib/backend", () => ({get: vi.fn(() => Promise.resolve([]))}));
import { clearLocalActivity, observeActivity, livingActivity, pulses, setCloudActivity } from "@/lib/living-activity";
beforeEach(clearLocalActivity);
const send=(topic:string, event:Record<string,unknown>) => observeActivity({topic,ts:1,...event});
it("uses actual stream transitions and retains simultaneous training", () => {
  expect(pulses(livingActivity.getState())).toEqual(["idle"]);
  send("chat",{kind:"start",message_key:"reply"});
  expect(pulses(livingActivity.getState())).toEqual(["thinking"]);
  send("chat",{kind:"token",message_key:"reply"});
  send("job",{job:{id:"train",kind:"train",status:"running"}});
  expect(pulses(livingActivity.getState())).toEqual(["generating","training"]);
  send("chat",{kind:"done",message_key:"reply"});
  expect(pulses(livingActivity.getState())).toEqual(["training"]);
  send("job",{job:{id:"train",kind:"train",status:"completed"}});
  expect(pulses(livingActivity.getState())).toEqual(["idle"]);
});
it("does not invent activity from unidentified events or retain stale streams after disconnect", () => {
  send("chat",{kind:"token"}); expect(pulses(livingActivity.getState())).toEqual(["idle"]);
  send("chat",{kind:"start",message_key:"reply"});
  send("connection",{connected:false});
  expect(pulses(livingActivity.getState())).toEqual(["offline"]);
  setCloudActivity(["evaluating"]);
  expect(pulses(livingActivity.getState())).toEqual(["evaluating","offline"]);
});

it('ignores a late reconnect snapshot after a newer terminal job event',async()=>{
  const backend=await import('@/lib/backend');
  let resolve!:(v:any)=>void;vi.mocked(backend.get).mockImplementationOnce(()=>new Promise(r=>resolve=r));
  observeActivity({topic:'connection',ts:1,connected:true});
  observeActivity({topic:'job',ts:2,job:{id:'completed',kind:'train',status:'completed'}});
  resolve([{id:'completed',kind:'train',status:'running'}]);await Promise.resolve();
  expect(pulses(livingActivity.getState())).not.toContain('training');
});
