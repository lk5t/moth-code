import { useEffect, useState } from "react";
import { ScrollText } from "lucide-react";
import { get, post, put } from "@/lib/backend";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea, Input, Label } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

interface Policy {
  system_prompt: string;
  generation_defaults: Record<string, number>;
  content_rules: unknown[];
}

const EXAMPLE = `[
  {
    "id": "example-redact",
    "description": "Mask a word in responses",
    "applies_to": "output",
    "match": { "type": "keywords", "patterns": ["example"] },
    "action": "redact"
  }
]`;

/** Owner-controlled conversational policy. Separate from operational security. */
export function PolicySection() {
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [rules, setRules] = useState("[]");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [test, setTest] = useState("");
  const [testResult, setTestResult] = useState<string | null>(null);

  useEffect(() => {
    get<Policy>("/api/policy").then((p) => {
      setPolicy(p);
      setRules(JSON.stringify(p.content_rules, null, 2));
    });
  }, []);
  if (!policy) return null;

  const save = async () => {
    try {
      const parsed = JSON.parse(rules);
      const saved = await put<Policy>("/api/policy", { ...policy, content_rules: parsed });
      setPolicy(saved);
      setMsg({ ok: true, text: "Policy saved." });
    } catch (e) {
      setMsg({ ok: false, text: String((e as Error).message ?? e) });
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><ScrollText className="size-4 text-accent" />Content policy (owner-defined)</CardTitle>
        <CardDescription>
          You decide how MOTH behaves in conversation. MOTH ships with no topic restrictions; add your own rules below.
          Operational protections (workspace boundaries, approvals, credential safety) are separate and always on.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div>
          <Label>System prompt</Label>
          <Textarea className="mt-1" rows={3} value={policy.system_prompt} onChange={(e) => setPolicy({ ...policy, system_prompt: e.target.value })} />
        </div>
        <div className="grid grid-cols-5 gap-2">
          {Object.entries(policy.generation_defaults).map(([k, v]) => (
            <div key={k}>
              <Label>{k.replace(/_/g, " ")}</Label>
              <Input className="mt-1" type="number" step="any" value={v}
                onChange={(e) => setPolicy({ ...policy, generation_defaults: { ...policy.generation_defaults, [k]: Number(e.target.value) } })} />
            </div>
          ))}
        </div>
        <div>
          <div className="flex items-center justify-between">
            <Label>Rules (JSON)</Label>
            <button className="cursor-pointer text-[11px] text-muted hover:text-fg" onClick={() => setRules(EXAMPLE)}>Insert example</button>
          </div>
          <Textarea className="mt-1 font-mono text-xs" rows={8} value={rules} onChange={(e) => setRules(e.target.value)} spellCheck={false} />
          <div className="mt-1 text-[11px] text-faint">Each rule: id, applies_to (input | output | both), match.type (keywords | regex), match.patterns, action (block | warn | redact), optional message.</div>
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={save}>Save policy</Button>
          <Button variant="ghost" onClick={async () => {
            const p = await post<Policy>("/api/policy/reset");
            setPolicy(p);
            setRules(JSON.stringify(p.content_rules, null, 2));
            setMsg({ ok: true, text: "Policy reset to defaults." });
          }}>Reset</Button>
          {msg && <span className={msg.ok ? "text-xs text-success" : "text-xs text-danger"}>{msg.text}</span>}
        </div>
        <div className="flex items-center gap-2 border-t border-border pt-3">
          <Input placeholder="Test text against the saved policy" value={test} onChange={(e) => setTest(e.target.value)} />
          <Button variant="secondary" disabled={!test} onClick={async () => {
            const r = await post<any>("/api/policy/test", { text: test });
            setTestResult(`input: ${r.input.allowed ? "allowed" : "blocked"} · output: ${r.output.allowed ? JSON.stringify(r.output.text) : "blocked"}${r.output.triggered.length ? ` · rules: ${r.output.triggered.map((t: any) => t.id).join(", ")}` : ""}`);
          }}>Test</Button>
        </div>
        {testResult && <div className="font-mono text-[11px] text-muted">{testResult}</div>}
      </CardContent>
    </Card>
  );
}
