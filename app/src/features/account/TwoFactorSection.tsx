/** 1.0 Settings → Account → Two-factor sign-in (authenticator-app codes). */
import { useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { serverApi, useAccount } from "@/lib/account";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function TwoFactorSection() {
  const user = useAccount((s) => s.user);
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [setup, setSetup] = useState<{ secret: string; uri: string } | null>(null);
  const [code, setCode] = useState(""), [password, setPassword] = useState("");
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => { if (user) serverApi<{ enabled: boolean }>("/v1/me/2fa").then((r) => setEnabled(r.enabled)).catch(() => setEnabled(null)); }, [user?.id]);
  if (!user || enabled === null) return null;
  const run = async (fn: () => Promise<void>) => { setNote(null); try { await fn(); } catch (e) { setNote(String((e as Error).message ?? e)); } };
  return <Card><CardHeader><CardTitle className="flex items-center gap-2"><ShieldCheck className="size-4 text-accent" />Two-factor sign-in</CardTitle>
    <CardDescription>{enabled ? "On: signing in also needs a code from your authenticator app." : "Protect your account with a code from an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password, …)."}</CardDescription></CardHeader>
    <CardContent className="flex flex-col gap-2 text-xs">
      {!enabled && !setup && <Button size="sm" className="self-start" onClick={() => void run(async () => setSetup(await serverApi("/v1/me/2fa/setup", { method: "POST" })))}>Turn on</Button>}
      {!enabled && setup && <>
        <p className="text-muted">Add this key to your authenticator app (choose “enter a setup key”), then type the 6-digit code it shows:</p>
        <code className="selectable rounded border border-border bg-bg px-2 py-1 font-mono tracking-wider">{setup.secret.match(/.{1,4}/g)?.join(" ")}</code>
        <div className="flex gap-2"><Input inputMode="numeric" maxLength={6} placeholder="123456" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
          <Button size="sm" disabled={code.length !== 6} onClick={() => void run(async () => {
            await serverApi("/v1/me/2fa/enable", { method: "POST", json: { code } }); setEnabled(true); setSetup(null); setCode(""); setNote("Two-factor sign-in is on.");
          })}>Confirm</Button></div>
      </>}
      {enabled && <div className="flex flex-wrap gap-2">
        <Input type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} className="max-w-44" />
        <Input inputMode="numeric" maxLength={6} placeholder="Code" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} className="max-w-28" />
        <Button size="sm" variant="secondary" disabled={!password || code.length !== 6} onClick={() => void run(async () => {
          await serverApi("/v1/me/2fa/disable", { method: "POST", json: { code, password } }); setEnabled(false); setCode(""); setPassword(""); setNote("Two-factor sign-in is off.");
        })}>Turn off</Button></div>}
      {note && <p role="status" className="text-muted">{note}</p>}
    </CardContent></Card>;
}
