import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Group, Panel, Separator, usePanelRef } from "react-resizable-panels";
import { PanelLeft, PanelRight, SquareTerminal } from "lucide-react";
import { appStore, useApp } from "@/lib/app-state";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tip } from "@/components/ui/tooltip";
import { ChatPanel } from "@/features/chat/ChatPanel";
import { Explorer } from "./Explorer";
// 0.9.1: the code editor (Monaco) and terminal (xterm) are several MB; load them only when shown
const EditorPanel = lazy(() => import("./EditorPanel").then((m) => ({ default: m.EditorPanel })));
const TerminalPanel = lazy(() => import("./TerminalPanel").then((m) => ({ default: m.TerminalPanel })));
const PanelLoading = ({ what }: { what: string }) => (
  <div role="status" className="flex h-full items-center justify-center gap-2 text-xs text-faint">
    <span className="size-1.5 animate-ping rounded-full bg-accent" />Loading {what}…
  </div>
);
import { ChangesPanel } from "./ChangesPanel";
import { ActivityPanel } from "./ActivityPanel";
import { ProjectIntelligencePanel } from "@/features/agent/ProjectIntelligencePanel";
import { ErrorNotice } from "@/components/ErrorNotice";
import { Select } from "@/components/ui/select";
import { pickProject, openProjectPath } from "./project-actions";

export function WorkspaceView() {
  const explorerOpen = useApp((s) => s.explorerOpen);
  const toolsOpen = useApp((s) => s.toolsOpen);
  const terminalOpen = useApp((s) => s.terminalOpen);
  const rightTab = useApp((s) => s.rightTab);
  const project = useApp((s) => s.project);
  const projects = useApp((s) => s.projects);
  const [projectError,setProjectError]=useState<string|null>(null);
  const [opening,setOpening]=useState(false);
  const chooseProject=async(path?:string)=>{setProjectError(null);setOpening(true);try {if(path) await openProjectPath(path);else await pickProject();}
    catch(error) {setProjectError((error as Error).message);}finally {setOpening(false);}};
  const explorer = usePanelRef();
  const tools = usePanelRef();
  const initialLayout = useRef(appStore.getState().workspaceLayout);

  useEffect(() => {
    const p = explorer.current;
    if (!p) return;
    if (explorerOpen && p.isCollapsed()) {
      p.expand();
      if (p.getSize().asPercentage < 14) p.resize("18%");
    }
    if (!explorerOpen && !p.isCollapsed()) p.collapse();
  }, [explorerOpen]);
  useEffect(() => {
    const p = tools.current;
    if (!p) return;
    if (toolsOpen && p.isCollapsed()) {
      p.expand();
      if (p.getSize().asPercentage < 30) p.resize("50%");
    }
    if (!toolsOpen && !p.isCollapsed()) p.collapse();
  }, [toolsOpen]);

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col">
      <header className="flex h-8 shrink-0 items-center gap-1 border-b border-border px-1">
        <Tip label="Toggle explorer" side="bottom">
          <Button variant="ghost" size="icon-sm" onClick={() => appStore.setState((s) => ({ explorerOpen: !s.explorerOpen }))}>
            <PanelLeft />
          </Button>
        </Tip>
        <button
          className="ml-1 cursor-pointer truncate rounded px-2 py-1 text-xs text-muted hover:bg-surface-2 hover:text-fg"
          disabled={opening} onClick={()=>chooseProject()}
          title="Open another workspace folder"
        >
          {project ? project.name : "Open folder…"}
        </button>
        {projects.length > 0 && <Select disabled={opening} aria-label="Recent projects" className="ml-2 h-7 max-w-48 text-xs" value={project?.id ?? ""}
          onChange={(event) => {const chosen=projects.find((p)=>p.id === Number(event.target.value));if(chosen) void chooseProject(chosen.path);}}>
          <option value="" disabled>Recent projects</option>{projects.map((p)=><option key={p.id} value={p.id}>{p.name}</option>)}
        </Select>}
        <div className="flex-1" />
        <Tip label="Terminal" side="bottom">
          <Button
            variant="ghost"
            size="icon-sm"
            className={terminalOpen ? "text-fg" : ""}
            onClick={() => appStore.setState((s) => ({ terminalOpen: !s.terminalOpen, toolsOpen: true }))}
          >
            <SquareTerminal />
          </Button>
        </Tip>
        <Tip label="Toggle tools panel" side="bottom">
          <Button variant="ghost" size="icon-sm" onClick={() => appStore.setState((s) => ({ toolsOpen: !s.toolsOpen }))}>
            <PanelRight />
          </Button>
        </Tip>
      </header>
      <ErrorNotice error={projectError} />
      <Group orientation="horizontal" className="min-h-0 flex-1" defaultLayout={initialLayout.current}
        onLayoutChanged={(layout) => appStore.setState({ workspaceLayout: layout })}>
        <Panel
          id="explorer"
          panelRef={explorer}
          defaultSize="16%"
          minSize="12%"
          collapsible
          collapsedSize={0}
          onResize={(size) => {
            const collapsed = size.asPercentage === 0;
            if (collapsed === appStore.getState().explorerOpen) appStore.setState({ explorerOpen: !collapsed });
          }}
          className="bg-surface"
        >
          <Explorer onOpenProject={pickProject} />
        </Panel>
        <Separator />
        <Panel id="conversation" defaultSize="34%" minSize="25%">
          <ChatPanel />
        </Panel>
        <Separator />
        <Panel
          id="tools"
          panelRef={tools}
          defaultSize="50%"
          minSize="20%"
          collapsible
          collapsedSize={0}
          onResize={(size) => {
            const collapsed = size.asPercentage === 0;
            if (collapsed === appStore.getState().toolsOpen) appStore.setState({ toolsOpen: !collapsed });
          }}
        >
          <Group orientation="vertical">
            <Panel defaultSize="65%" minSize="20%">
              <Tabs value={rightTab === "memory" ? "project" : rightTab} onValueChange={(v) => appStore.setState({ rightTab: v })} className="flex h-full flex-col">
                <TabsList className="h-9 shrink-0 border-b border-border px-1">
                  <TabsTrigger value="editor">Editor</TabsTrigger>
                  <TabsTrigger value="changes">Changes</TabsTrigger>
                  <TabsTrigger value="activity">Activity</TabsTrigger>
                  <TabsTrigger value="project">Project</TabsTrigger>
                </TabsList>
                <TabsContent value="editor" className="min-h-0 flex-1"><Suspense fallback={<PanelLoading what="the editor" />}><EditorPanel /></Suspense></TabsContent>
                <TabsContent value="changes" className="min-h-0 flex-1"><ChangesPanel /></TabsContent>
                <TabsContent value="activity" className="min-h-0 flex-1"><ActivityPanel /></TabsContent>
                <TabsContent value="project" className="min-h-0 flex-1"><ProjectIntelligencePanel /></TabsContent>
              </Tabs>
            </Panel>
            {terminalOpen && <Separator />}
            {terminalOpen && (
              <Panel defaultSize="35%" minSize="12%">
                <Suspense fallback={<PanelLoading what="the terminal" />}><TerminalPanel /></Suspense>
              </Panel>
            )}
          </Group>
        </Panel>
      </Group>
    </div>
  );
}
