import { useState } from "react";
import { ShieldCheck } from "lucide-react";
import { createStore } from "@/lib/store";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

const store = createStore<{ resolve: ((pw: string | null) => void) | null }>({ resolve: null });

/** Ask the user to re-enter their password (used for sensitive operations). */
export function askPassword(): Promise<string | null> {
  return new Promise((resolve) => store.setState({ resolve }));
}

export function ReauthDialog() {
  const resolve = store.useStore((s) => s.resolve);
  const [pw, setPw] = useState("");
  const done = (v: string | null) => {
    resolve?.(v);
    store.setState({ resolve: null });
    setPw("");
  };
  return (
    <Dialog open={!!resolve} onOpenChange={(o) => !o && done(null)}>
      <DialogContent className="w-[380px]">
        <div className="flex items-center gap-2"><ShieldCheck className="size-4 text-accent" /><DialogTitle>Confirm it's you</DialogTitle></div>
        <DialogDescription>This action needs your password again.</DialogDescription>
        <form className="mt-4 flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); done(pw); }}>
          <Input type="password" autoFocus placeholder="Password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => done(null)}>Cancel</Button>
            <Button type="submit" disabled={!pw}>Confirm</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
