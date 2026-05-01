import { useState } from "react";
import { ChevronDown, Sparkles, Wrench } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { formatTs, cn } from "@/lib/utils";

const AGENT_LABEL: Record<string, string> = {
  context_builder: "Context",
  care_plan: "Care plan",
  engagement: "Engagement",
};

const AGENT_TONE: Record<string, string> = {
  context_builder: "bg-sky-50 text-sky-700 border-sky-200",
  care_plan: "bg-mint-soft text-mint-ink border-mint",
  engagement: "bg-amber-50 text-amber-700 border-amber-200",
};

function summarize(value: any): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    if (value.length === 0) return "—";
    return value
      .slice(0, 4)
      .map((v) => (typeof v === "string" ? v : v && (v.label || v.name || v.id) ? (v.label || v.name || v.id) : null))
      .filter(Boolean)
      .join(", ") || `${value.length} items`;
  }
  if (typeof value === "object") {
    const keys = Object.keys(value);
    return keys.slice(0, 3).map((k) => `${k}: ${summarize((value as any)[k])}`).join(" · ");
  }
  return "";
}

export function AIInsightCard({ trace }: { trace: any }) {
  const [open, setOpen] = useState(false);
  const agent = trace.agent_name || "agent";
  const observed = summarize(trace.observed);
  const inferred = summarize(trace.inferred);

  return (
    <div className="card-base overflow-hidden">
      <div className="flex items-start gap-3 p-4">
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-mint-soft text-mint-deep">
          <Sparkles className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge className={cn("border", AGENT_TONE[agent] || "bg-muted text-ink-60 border-border")}>
              {AGENT_LABEL[agent] || agent}
            </Badge>
            <span className="text-xs text-ink-40">{formatTs(trace.timestamp || trace.created_at)}</span>
          </div>
          <p className="mt-2 text-sm font-medium text-ink-DEFAULT">{trace.decided || "—"}</p>
          {(observed || inferred) && (
            <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1 text-xs text-ink-60 sm:grid-cols-2">
              {observed && (
                <div>
                  <dt className="font-semibold uppercase tracking-wide text-ink-40">Observed</dt>
                  <dd className="line-clamp-2">{observed}</dd>
                </div>
              )}
              {inferred && (
                <div>
                  <dt className="font-semibold uppercase tracking-wide text-ink-40">Inferred</dt>
                  <dd className="line-clamp-2">{inferred}</dd>
                </div>
              )}
            </dl>
          )}
          {Array.isArray(trace.tools_called) && trace.tools_called.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-ink-40">
              <Wrench className="h-3 w-3" />
              {trace.tools_called.map((t: string) => (
                <span key={t} className="chip">{t}</span>
              ))}
            </div>
          )}
          <button
            type="button"
            className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-ink-40 hover:text-ink-DEFAULT"
            onClick={() => setOpen((v) => !v)}
          >
            <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")} />
            {open ? "Hide details" : "Show details"}
          </button>
          {open && (
            <div className="mt-2 grid gap-2 text-xs">
              <DetailBlock label="Observed" value={trace.observed} />
              <DetailBlock label="Inferred" value={trace.inferred} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function DetailBlock({ label, value }: { label: string; value: any }) {
  if (value == null) return null;
  return (
    <div className="rounded-lg border border-border bg-muted px-3 py-2">
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-ink-40">{label}</div>
      <pre className="whitespace-pre-wrap text-xs text-ink-DEFAULT">{JSON.stringify(value, null, 2)}</pre>
    </div>
  );
}
