import { useState } from "react";
import { IntelligenceView } from "@/features/intelligence/IntelligenceView";
import { ActivityPanel } from "@/features/workspace/ActivityPanel";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

/** Existing measured history and local events, one authoritative navigation home. */
export function ActivityWorkspace() {
  const [tab, setTab] = useState("evolution");
  return <div className="h-full overflow-auto p-3 sm:p-5"><div className="mx-auto max-w-6xl space-y-3">
    <header><h1 className="text-2xl font-medium">Activity</h1><p className="mt-1 text-xs text-muted">Recorded model changes and events on this computer.</p></header>
    <Tabs value={tab} onValueChange={setTab}><TabsList aria-label="Activity sections">
      <TabsTrigger value="evolution">Evolution timeline</TabsTrigger><TabsTrigger value="local">This computer</TabsTrigger>
    </TabsList><TabsContent value="evolution"><IntelligenceView embedded /></TabsContent>
      <TabsContent value="local"><ActivityPanel all /></TabsContent>
    </Tabs>
  </div></div>;
}
