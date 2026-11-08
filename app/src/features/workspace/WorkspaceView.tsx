import { useEffect, useRef } from "react";
import { Group, Panel, Separator, usePanelRef } from "react-resizable-panels";
import { PanelLeft, PanelRight, SquareTerminal } from "lucide-react";
import { appStore, useApp } from "@/lib/app-state";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tip } from "@/components/ui/tooltip";
import { ChatPanel } from "@/features/chat/ChatPanel";
import { Explorer } from "./Explorer";
import { EditorPanel } from "./EditorPanel";
import { TerminalPanel } from "./TerminalPanel";
import { ChangesPanel } from "./ChangesPanel";
import { ActivityPanel } from "./ActivityPanel";
import { MemoryPanel } from "@/features/agent/MemoryPanel";
import { pickProject } from "./project-actions";

export function WorkspaceView() {
  const explorerOpen = useApp((s) => s.explorerOpen);
  const toolsOpen = useApp((s) => s.toolsOpen);
  const terminalOpen = useApp((s) => s.terminalOpen);
  const rightTab = useApp((s) => s.rightTab);
  const project = useApp((s) => s.project);
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
      if (p.getSize().asPercentage < 30) p.resize("42%");
    }
    if (!toolsOpen && !p.isCollapsed()) p.collapse();
  }, [toolsOpen]);

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col">
      <header className="flex h-10 shrink-0 items-center gap-1 border-b border-border px-2">
        <Tip label="Toggle explorer" side="bottom">
          <Button variant="ghost" size="icon" onClick={() => appStore.setState((s) => ({ explorerOpen: !s.explorerOpen }))}>
            <PanelLeft />
          </Button>
        </Tip>
        <button
          className="ml-1 cursor-pointer truncate rounded px-2 py-1 text-xs text-muted hover:bg-surface-2 hover:text-fg"
          onClick={pickProject}
          title="Open another workspace folder"
        >
          {project ? project.name : "Open folder…"}
        </button>
        <div className="flex-1" />
        <Tip label="Terminal" side="bottom">
          <Button
            variant="ghost"
            size="icon"
            className={terminalOpen ? "text-fg" : ""}
            onClick={() => appStore.setState((s) => ({ terminalOpen: !s.terminalOpen, toolsOpen: true }))}
          >
            <SquareTerminal />
          </Button>
        </Tip>
        <Tip label="Toggle tools panel" side="bottom">
          <Button variant="ghost" size="icon" onClick={() => appStore.setState((s) => ({ toolsOpen: !s.toolsOpen }))}>
            <PanelRight />
          </Button>
        </Tip>
      </header>
      <Group orientation="horizontal" className="min-h-0 flex-1" defaultLayout={initialLayout.current}
        onLayoutChanged={(layout) => appStore.setState({ workspaceLayout: layout })}>
        <Panel
          id="explorer"
          panelRef={explorer}
          defaultSize="18%"
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
        <Panel id="conversation" defaultSize="40%" minSize="25%">
          <ChatPanel />
        </Panel>
        <Separator />
        <Panel
          id="tools"
          panelRef={tools}
          defaultSize="42%"
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
              <Tabs value={rightTab} onValueChange={(v) => appStore.setState({ rightTab: v })} className="flex h-full flex-col">
                <TabsList className="h-9 shrink-0 border-b border-border px-1">
                  <TabsTrigger value="editor">Editor</TabsTrigger>
                  <TabsTrigger value="changes">Changes</TabsTrigger>
                  <TabsTrigger value="activity">Activity</TabsTrigger>
                  <TabsTrigger value="memory">Memory</TabsTrigger>
                </TabsList>
                <TabsContent value="editor" className="min-h-0 flex-1"><EditorPanel /></TabsContent>
                <TabsContent value="changes" className="min-h-0 flex-1"><ChangesPanel /></TabsContent>
                <TabsContent value="activity" className="min-h-0 flex-1"><ActivityPanel /></TabsContent>
                <TabsContent value="memory" className="min-h-0 flex-1"><MemoryPanel /></TabsContent>
              </Tabs>
            </Panel>
            {terminalOpen && <Separator />}
            {terminalOpen && (
              <Panel defaultSize="35%" minSize="12%">
                <TerminalPanel />
              </Panel>
            )}
          </Group>
        </Panel>
      </Group>
    </div>
  );
}
