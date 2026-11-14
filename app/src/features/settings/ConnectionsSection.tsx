/**
 * 1.0 Settings → Connections: link GitHub so MOTH can clone your repositories, push branches and open pull
 * requests — always on your click. The token stays in your computer's credential vault.
 */
import { useEffect, useState } from "react";
import { GitBranch as Github, Link2, Unlink } from "lucide-react";
import { forgetGithub, gh, githubToken, saveGithubToken, TOKEN_PAGE } from "@/lib/github";
import { openExternal } from "@/lib/external";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function ConnectionsSection() {
  const [who, setWho] = useState<{ login: string; avatar_url?: string } | null>(null);
  const [token, setToken] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    githubToken().then(async (t) => { if (t) setWho(await gh<{ login: string }>("/api/github/user", undefined, t)); }).catch(() => {});
  }, []);
  const connect = async () => {
    setBusy(true); setNote(null);
    try {
      const u = await gh<{ login: string; avatar_url?: string }>("/api/github/user", undefined, token.trim());
      await saveGithubToken(token.trim());
      setWho(u); setToken(""); setNote(`Connected as ${u.login}.`);
    } catch (e) { setNote(String((e as Error).message ?? e)); } finally { setBusy(false); }
  };
  return <Card><CardHeader><CardTitle className="flex items-center gap-2"><Link2 className="size-4 text-accent" />Connections</CardTitle>
    <CardDescription>Let MOTH work with your accounts. It only acts when you click, and you can disconnect any time.</CardDescription></CardHeader>
    <CardContent className="flex flex-col gap-3 text-xs">
      <div className="flex items-center gap-2"><Github className="size-4" /><span className="font-medium">GitHub</span>
        {who && <span className="text-success">connected as {who.login}</span>}</div>
      {who ? <div className="flex gap-2"><Button size="sm" variant="secondary" onClick={() => void forgetGithub().then(() => { setWho(null); setNote("Disconnected."); })}><Unlink /> Disconnect</Button></div>
        : <>
          <p className="text-muted">1. <button className="text-accent underline" onClick={() => void openExternal(TOKEN_PAGE)}>Create a token on GitHub</button> with
            access to the repositories you want (Contents and Pull requests: read and write). 2. Paste it here.</p>
          <div className="flex gap-2"><Input type="password" value={token} placeholder="github_pat_…" onChange={(e) => setToken(e.target.value)} />
            <Button size="sm" disabled={!token.trim() || busy} onClick={() => void connect()}>Connect</Button></div>
        </>}
      {note && <p role="status" className="text-muted">{note}</p>}
    </CardContent></Card>;
}
