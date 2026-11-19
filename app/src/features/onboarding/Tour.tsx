/** 2.1 guided tour: a few short steps, once, after the first sign-in (reopen it from Settings → Account). */
import { useState } from "react";
import { Command, FolderGit2, MessageSquare, Radar, Sparkles, SlidersHorizontal } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { createStore } from "@/lib/store";
import { cn } from "@/lib/utils";
import { navigate } from "@/lib/navigation";
import { useAccount } from "@/lib/account";

const KEY = "moth.tour.done";
function done(): boolean { try { return localStorage.getItem(KEY) === "1"; } catch { return true; } }
const tourStore = createStore({ open: !done() });
export const reopenTour = () => tourStore.setState({ open: true });
function finish() { try { localStorage.setItem(KEY, "1"); } catch { /* shown again next time */ } tourStore.setState({ open: false }); }

export const STEPS = [
  { icon: Sparkles, title: "Meet MOTH", text: "MOTH is an AI for coding and security that trains itself, every day, on a network of computers. It's young, so it gets better over time.", go: null },
  { icon: MessageSquare, title: "Chat", text: "Ask questions, paste errors, drop files or folders in. Code blocks get Copy and Apply buttons, and MOTH checks the code it writes.", go: "chat" },
  { icon: FolderGit2, title: "Projects and agent mode", text: "Open a folder and let MOTH write, run and fix code. You see every change before and after and choose Apply or Reject.", go: "workspace" },
  { icon: Radar, title: "Security, right in chat", text: "Say \"audit my code\", \"check my dependencies\" or \"scan 192.168.1.10\". Anything that contacts a system asks for your Yes first — only test what you own or may test.", go: "chat" },
  { icon: Command, title: "Ctrl+K finds everything", text: "Chats (even words inside them), projects, actions and settings — one shortcut away.", go: null },
  { icon: SlidersHorizontal, title: "Make it yours", text: "Settings → Appearance changes the app size (Ctrl + / Ctrl −) and animations. Your choices follow your account to your other computers.", go: "settings" },
] as const;

export function Tour() {
  const open = tourStore.useStore((s) => s.open);
  const signedIn = useAccount((s) => !!s.user);  // shown after the first sign-in, never over the sign-in itself
  const [i, setI] = useState(0);
  if (!open || !signedIn) return null;
  const step = STEPS[i], Icon = step.icon, last = i === STEPS.length - 1;
  return <Dialog open onOpenChange={(o) => { if (!o) finish(); }}>
    <DialogContent className="w-[26rem]">
      <div key={i} className="flex flex-col items-center gap-3 pt-2 text-center animate-slide-up">
        <span className="flex size-12 items-center justify-center rounded-2xl bg-accent-soft shadow-glow"><Icon className="size-6 text-accent" /></span>
        <DialogTitle className="text-base">{step.title}</DialogTitle>
        <DialogDescription className="text-[0.8125rem]">{step.text}</DialogDescription>
      </div>
      <div className="mt-4 flex justify-center gap-1.5" aria-label={`Step ${i + 1} of ${STEPS.length}`}>
        {STEPS.map((_, k) => <span key={k} className={cn("h-1.5 rounded-full transition-all duration-300", k === i ? "w-5 bg-accent" : "w-1.5 bg-surface-3")} />)}
      </div>
      <div className="mt-4 flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={finish}>Skip</Button>
        <div className="flex-1" />
        {i > 0 && <Button variant="secondary" size="sm" onClick={() => setI(i - 1)}>Back</Button>}
        {step.go && <Button variant="secondary" size="sm" onClick={() => { finish(); navigate(step.go!); }}>Show me</Button>}
        <Button size="sm" onClick={() => (last ? finish() : setI(i + 1))}>{last ? "Start" : "Next"}</Button>
      </div>
    </DialogContent>
  </Dialog>;
}
