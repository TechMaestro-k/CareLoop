import { useEffect, useState } from "react";
import { RefreshCw, Save } from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";

export default function PromptsPage() {
  const [prompts, setPrompts] = useState<any[]>([]);
  const [active, setActive] = useState<string>("");
  const [draft, setDraft] = useState<string>("");
  const [original, setOriginal] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [reloading, setReloading] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function load() {
    const d = await api.listPrompts();
    setPrompts(d.prompts || []);
    if (!active && d.prompts?.[0]) {
      setActive(d.prompts[0].key);
      setDraft(d.prompts[0].user || "");
      setOriginal(d.prompts[0].user || "");
    }
  }

  async function forceReload() {
    setReloading(true);
    setMsg(null);
    try {
      const r = await api.reloadPrompts();
      setPrompts(r.prompts || []);
      setMsg(
        `Cache cleared (${r.cleared.yaml_cleared} YAML, ${r.cleared.resolved_cleared} resolved).`,
      );
    } catch (e: any) {
      setMsg(`Reload failed: ${e.message}`);
    } finally {
      setReloading(false);
    }
  }
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function pick(key: string) {
    const p = prompts.find((x: any) => x.key === key);
    setActive(key);
    setDraft(p?.user || "");
    setOriginal(p?.user || "");
    setMsg(null);
  }

  async function save() {
    setSaving(true);
    setMsg(null);
    try {
      await api.updatePrompt(active, draft);
      setOriginal(draft);
      setMsg("Saved. New prompt takes effect on the next agent call.");
      void load();
    } catch (e: any) {
      setMsg(`Error: ${e.message}`);
    } finally {
      setSaving(false);
    }
  }

  const current = prompts.find((p: any) => p.key === active);
  const dirty = draft !== original;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-display text-2xl font-bold tracking-tight">Prompt registry</h2>
          <p className="text-sm text-ink-60">
            Edit any agent prompt live. Saves are stored in Supabase and override the YAML file.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={forceReload} disabled={reloading}>
          <RefreshCw className="h-3.5 w-3.5" />
          {reloading ? "Reloading…" : "Force-reload cache"}
        </Button>
      </div>
      <div className="grid gap-4 md:grid-cols-[260px_1fr]">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Prompts</CardTitle>
          </CardHeader>
          <CardContent className="p-2">
            <ul className="space-y-1">
              {prompts.map((p: any) => (
                <li key={p.key}>
                  <button
                    onClick={() => pick(p.key)}
                    className={`flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm transition focus-ring ${
                      active === p.key
                        ? "bg-mint-soft text-mint-ink font-medium"
                        : "hover:bg-muted text-ink-DEFAULT"
                    }`}
                  >
                    <span className="truncate">{p.key}</span>
                    {p.overridden && (
                      <Badge className="border-triage-amber/40 bg-triage-amberSoft text-triage-amber">
                        edited
                      </Badge>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{active || "Pick a prompt"}</CardTitle>
            <CardDescription>
              {current?.description ||
                "Edit the user template. System prompt and model are fixed in code."}
            </CardDescription>
            <div className="flex flex-wrap gap-2 text-xs text-ink-40">
              {current?.model && (
                <Badge className="border-border bg-muted text-ink-60">
                  model: {current.model}
                </Badge>
              )}
              {current?.temperature != null && (
                <Badge className="border-border bg-muted text-ink-60">
                  temp: {current.temperature}
                </Badge>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {current?.system && (
              <div>
                <div className="mb-1 text-xs font-semibold uppercase text-ink-40">
                  System (read-only)
                </div>
                <pre className="rounded-lg bg-muted p-3 text-xs whitespace-pre-wrap text-ink-DEFAULT">
                  {current.system}
                </pre>
              </div>
            )}
            <div>
              <div className="mb-1 text-xs font-semibold uppercase text-ink-40">
                User template (editable)
              </div>
              <Textarea
                rows={20}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                className="font-mono text-xs"
              />
            </div>
            <div className="flex items-center gap-3">
              <Button onClick={save} disabled={!dirty || saving}>
                <Save className="h-4 w-4" />
                {saving ? "Saving…" : "Save"}
              </Button>
              {dirty && <span className="text-xs text-triage-amber">unsaved changes</span>}
              {msg && <span className="text-xs text-mint-ink">{msg}</span>}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
