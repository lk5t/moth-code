import { useState } from "react";
import { Plus, X } from "lucide-react";
import { useResource } from "@/lib/hooks";
import { useApp } from "@/lib/app-state";
import { Input, Label } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export interface SourceSel {
  spec: string;
  license: string;
  max_bytes?: number | null;
}

interface CatalogEntry {
  id: string;
  spec: string;
  name: string;
  license: string;
  notes: string;
  download: boolean;
  gated?: boolean;
}

/** Choose licensed training data. Every source must carry a license. */
export function SourcePicker({ value, onChange }: { value: SourceSel[]; onChange: (v: SourceSel[]) => void }) {
  const { data: catalog } = useResource<CatalogEntry[]>("/api/training/catalog", [], []);
  const project = useApp((s) => s.project);
  const [folder, setFolder] = useState("");
  const [license, setLicense] = useState("");
  const has = (spec: string) => value.some((v) => v.spec === spec);
  const toggle = (c: CatalogEntry) =>
    onChange(has(c.spec) ? value.filter((v) => v.spec !== c.spec) : [...value, { spec: c.spec, license: c.license }]);
  const custom = value.filter((v) => !catalog?.some((c) => c.spec === v.spec));

  return (
    <div className="flex flex-col gap-2">
      {catalog?.map((c) => (
        <label key={c.id} className="flex cursor-pointer items-start gap-2.5 rounded-md border border-border p-2.5 hover:border-border-strong">
          <input type="checkbox" className="mt-0.5 accent-[#C1121F]" checked={has(c.spec)} onChange={() => toggle(c)} />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-1.5 text-[13px]">
              {c.name} <Badge>{c.license}</Badge>
              {c.download && <Badge variant="warning">download</Badge>}
              {c.gated && <Badge variant="warning">accept terms first</Badge>}
            </div>
            <div className="mt-0.5 text-xs text-muted">{c.notes}</div>
          </div>
        </label>
      ))}
      {custom.map((v) => (
        <div key={v.spec} className="flex items-center justify-between rounded-md border border-border px-2.5 py-1.5 text-xs">
          <span className="truncate">{v.spec.replace(/^dir:/, "📁 ")}</span>
          <span className="flex items-center gap-2">
            <Badge>{v.license}</Badge>
            <button className="cursor-pointer text-muted hover:text-fg" onClick={() => onChange(value.filter((x) => x !== v))}><X className="size-3" /></button>
          </span>
        </div>
      ))}
      <div className="rounded-md border border-dashed border-border p-2.5">
        <Label>Add a local folder you have the right to train on</Label>
        <div className="mt-1.5 flex gap-2">
          <Input placeholder="Folder path" value={folder} onChange={(e) => setFolder(e.target.value)} />
          <Input placeholder="License (e.g. MIT)" className="w-40" value={license} onChange={(e) => setLicense(e.target.value)} />
          <Button
            variant="secondary"
            size="icon"
            disabled={!folder.trim() || !license.trim()}
            onClick={() => {
              onChange([...value, { spec: `dir:${folder.trim()}`, license: license.trim() }]);
              setFolder("");
              setLicense("");
            }}
          >
            <Plus />
          </Button>
        </div>
        {project && (
          <button className="mt-1.5 cursor-pointer text-[11px] text-muted hover:text-fg" onClick={() => setFolder(project.path)}>
            Use open workspace ({project.name})
          </button>
        )}
      </div>
    </div>
  );
}
