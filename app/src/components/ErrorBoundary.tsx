import { Component, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { MothEmblem } from "./MothEmblem";

interface State {
  error: Error | null;
}

/** Keeps a rendering crash in one view from taking down the whole window. */
export class ErrorBoundary extends Component<{ children: ReactNode; label?: string }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: { componentStack?: string | null }) {
    console.error("MOTH UI error", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
        <MothEmblem className="size-10 opacity-70" />
        <div className="text-sm">{this.props.label ?? "This view"} hit an unexpected error</div>
        <pre className="selectable max-h-40 max-w-xl overflow-auto rounded border border-border bg-surface p-2 text-left text-[11px] text-muted">
          {this.state.error.message}
        </pre>
        <Button variant="secondary" onClick={() => this.setState({ error: null })}>Try again</Button>
      </div>
    );
  }
}
