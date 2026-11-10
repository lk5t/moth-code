import { CloudActivity } from "./CloudActivity";
import { useSavedSection } from "@/lib/use-saved-section";
import { openIntelligence } from "@/lib/app-state";
import { Button } from "@/components/ui/button";
import { ActivityPanel } from "@/features/workspace/ActivityPanel";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

/** Existing measured history and local events, one authoritative navigation home. */
export function ActivityWorkspace() {
  const [tab, setTab] = useSavedSection("activity", ["events", "evolution", "local"], "events");
  return <div className="h-full overflow-auto p-3 sm:p-5"><div className="mx-auto max-w-6xl space-y-3">
    <header><h1 className="text-2xl font-medium">Activity</h1><p className="mt-1 text-xs text-muted">Recorded model changes and events on this computer.</p></header>
    <Tabs value={tab} onValueChange={setTab}><TabsList aria-label="Activity sections">
      <TabsTrigger value="events">Cloud events</TabsTrigger><TabsTrigger value="evolution">Evolution timeline</TabsTrigger><TabsTrigger value="local">This computer</TabsTrigger>
    </TabsList><TabsContent value="events"><CloudActivity /></TabsContent><TabsContent value="evolution"><p className="text-xs text-muted">Model revisions, evaluations, promotions and rollbacks have one home.<Button size="sm" variant="secondary" onClick={()=>openIntelligence("history")}>Open Intelligence History</Button></p></TabsContent>
      <TabsContent value="local"><ActivityPanel all /></TabsContent>
    </Tabs>
  </div></div>;
}
