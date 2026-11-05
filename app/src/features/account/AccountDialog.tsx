import { useEffect, useState } from "react";
import { createStore } from "@/lib/store";
import { accountStore, forgotPassword, login, register, resendVerification, ServerError, setServerUrl, useAccount } from "@/lib/account";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { MothEmblem } from "@/components/MothEmblem";

type Mode = "login" | "register" | "forgot" | "sent";
export const accountDialog = createStore<{ open: boolean; mode: Mode; username: string; referral: string }>({
  open: false, mode: "login", username: "", referral: "",
});
export const openAccountDialog = (mode: Mode = "login", username = "") =>
  accountDialog.setState({ open: true, mode, username });

export function AccountDialog() {
  const { open, mode, username: presetUser, referral } = accountDialog.useStore((s) => s);
  const serverUrl = useAccount((s) => s.serverUrl);
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [code, setCode] = useState("");
  const [server, setServer] = useState(serverUrl);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [unverified, setUnverified] = useState(false);

  useEffect(() => {
    if (open) {
      setUsername(presetUser);
      setPassword("");
      setError(null);
      setInfo(null);
      setUnverified(false);
      setServer(accountStore.getState().serverUrl);
      setCode(referral);
    }
  }, [open, mode]);

  const go = (m: Mode) => accountDialog.setState({ mode: m });
  const close = () => accountDialog.setState({ open: false });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (server !== accountStore.getState().serverUrl) setServerUrl(server);
      if (mode === "login") {
        await login(username, password, remember);
        close();
      } else if (mode === "register") {
        const r = await register(username, email, password, code);
        setInfo(r.message);
        go("sent");
      } else if (mode === "forgot") {
        const r = await forgotPassword(username);
        setInfo(r.message);
        go("sent");
      }
    } catch (err) {
      const se = err as ServerError;
      setUnverified(se.reason === "email_unverified");
      setError(se.status === 429 ? `Too many attempts. Try again in ${se.retryAfter || 60}s.` : se.message);
    } finally {
      setBusy(false);
    }
  };

  const titles: Record<Mode, string> = {
    login: "Sign in to MOTH", register: "Create your MOTH account", forgot: "Reset your password", sent: "Check your email",
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && close()}>
      <DialogContent className="w-[400px]">
        <div className="mb-1 flex flex-col items-center gap-2 text-center">
          <MothEmblem className="size-12" glow />
          <DialogTitle className="text-base">{titles[mode]}</DialogTitle>
          <DialogDescription className="mt-0">
            {mode === "login" && "Local features work without an account. Sign in for MOTH Cloud, referrals and training."}
            {mode === "register" && "Usernames are unique and not case-sensitive."}
            {mode === "forgot" && "Enter your username or email."}
          </DialogDescription>
        </div>
        {mode === "sent" ? (
          <div className="mt-3 flex flex-col gap-3 text-center text-xs text-muted">
            <p>{info}</p>
            <Button onClick={() => go("login")}>Back to sign in</Button>
          </div>
        ) : (
          <form className="mt-3 flex flex-col gap-3" onSubmit={submit}>
            <div>
              <Label>{mode === "forgot" ? "Username or email" : "Username"}</Label>
              <Input className="mt-1" autoFocus value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
            </div>
            {mode === "register" && (
              <div>
                <Label>Email</Label>
                <Input className="mt-1" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required />
              </div>
            )}
            {mode !== "forgot" && (
              <div>
                <div className="flex items-center justify-between">
                  <Label>Password</Label>
                  {mode === "login" && <button type="button" className="cursor-pointer text-[11px] text-muted hover:text-fg" onClick={() => go("forgot")}>Forgot password?</button>}
                </div>
                <Input className="mt-1" type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                  autoComplete={mode === "register" ? "new-password" : "current-password"} required minLength={mode === "register" ? 10 : 1} />
              </div>
            )}
            {mode === "register" && (
              <div>
                <Label>Referral code (optional)</Label>
                <Input className="mt-1 uppercase" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} maxLength={16} />
              </div>
            )}
            {mode === "login" && (
              <label className="flex items-center gap-2 text-xs text-muted">
                <input type="checkbox" className="accent-[#C1121F]" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
                Remember me on this computer
              </label>
            )}
            {error && (
              <div className="rounded-md border border-danger/30 bg-danger/10 px-2.5 py-1.5 text-xs text-danger">
                {error}
                {unverified && (
                  <button type="button" className="ml-1 cursor-pointer underline" onClick={async () => setInfo((await resendVerification(username)).message)}>
                    Resend email
                  </button>
                )}
              </div>
            )}
            {info && <div className="text-xs text-muted">{info}</div>}
            <Button type="submit" disabled={busy}>
              {busy ? "Please wait…" : mode === "login" ? "Sign in" : mode === "register" ? "Create account" : "Send reset link"}
            </Button>
            <div className="text-center text-xs text-muted">
              {mode === "login" ? (
                <>New to MOTH? <button type="button" className="cursor-pointer text-fg hover:underline" onClick={() => go("register")}>Create an account</button></>
              ) : (
                <button type="button" className="cursor-pointer text-fg hover:underline" onClick={() => go("login")}>Back to sign in</button>
              )}
            </div>
            <details className="text-[11px] text-faint">
              <summary className="cursor-pointer">Server: {server || "not configured"}</summary>
              <Input className="mt-1 h-7 text-xs" placeholder="https://your-moth-server" value={server} onChange={(e) => setServer(e.target.value.trim())} />
            </details>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
