import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, CheckCircle2, RotateCcw, X } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { TriageBadge } from "@/components/TriageBadge";
import { AIInsightCard } from "@/components/AIInsightCard";
import { EmptyState } from "@/components/EmptyState";
import { api } from "@/lib/api";
import { formatTs, severityClass, triageBarClass } from "@/lib/utils";

export default function EscalationDetailPage() {
  const params = useParams<{ escId: string }>();
  const id = params.escId!;
  const navigate = useNavigate();
  const [data, setData] = useState<any>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const d = await api.getEscalation(id);
      setData(d);
    } catch (e: any) {
      setError(e?.message || "Failed to load");
    }
  }
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function act(action: string) {
    setBusy(true);
    setError(null);
    try {
      await api.actionEscalation(id, action, note);
      await load();
      setTimeout(() => navigate("/doctor/inbox"), 600);
    } catch (e: any) {
      setError(e?.message || "Action failed");
    } finally {
      setBusy(false);
    }
  }

  if (error && !data) {
    return <div className="card-base border-triage-red/30 bg-triage-redSoft p-3 text-sm text-triage-red">{error}</div>;
  }
  if (!data) return <p className="text-sm text-ink-40">Loading…</p>;
  const { escalation, patient, clinical, sdoh, interactions, reasoning_traces } = data;

  return (
    <div className="space-y-5">
      <Link to="/doctor/inbox" className="inline-flex items-center gap-1 text-sm text-ink-40 hover:text-ink-DEFAULT">
        <ArrowLeft className="h-3.5 w-3.5" /> Inbox
      </Link>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-2xl font-bold tracking-tight">
            {patient?.name}{" "}
            <span className="text-base font-normal text-ink-40">
              · {patient?.age}y · {patient?.phone}
            </span>
          </h2>
          <p className="text-sm text-ink-60">{clinical?.diagnosis}</p>
        </div>
        <div className="flex items-center gap-2">
          <TriageBadge severity={escalation.severity} />
          <Badge className="border-border bg-muted text-ink-60">{escalation.status}</Badge>
          <span className="text-xs text-ink-40">{formatTs(escalation.created_at)}</span>
        </div>
      </div>

      <Card className={triageBarClass(escalation.severity)}>
        <CardHeader><CardTitle>Agent brief</CardTitle></CardHeader>
        <CardContent>
          <pre className="whitespace-pre-wrap rounded-lg bg-muted p-3 text-sm text-ink-DEFAULT">
            {escalation.brief}
          </pre>
        </CardContent>
      </Card>

      <div className="grid gap-3 md:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>SDOH context</CardTitle></CardHeader>
          <CardContent className="space-y-1 text-sm">
            {sdoh ? (
              <>
                <Row k="Housing" v={sdoh.housing_risk} />
                <Row k="Transport" v={sdoh.transport_risk} />
                <Row k="Caregiver" v={sdoh.caregiver_risk} />
                <Row k="Literacy" v={sdoh.literacy_level} />
                <Row k="Digital comfort" v={sdoh.digital_comfort} />
                <Row k="Financial" v={sdoh.financial_risk} />
              </>
            ) : (
              <p className="text-ink-40">none</p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Recent interactions</CardTitle></CardHeader>
          <CardContent>
            {interactions?.length ? (
              <div className="space-y-2 max-h-72 overflow-auto pr-1">
                {interactions.map((it: any) => (
                  <div key={it.id} className="rounded-lg border border-border bg-surface p-2 text-xs">
                    <div className="flex items-center justify-between">
                      <Badge className={severityClass(it.classification)}>{it.direction}</Badge>
                      <span className="text-ink-40">{formatTs(it.timestamp)}</span>
                    </div>
                    <p className="mt-1 text-ink-DEFAULT">{it.content}</p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-ink-40">none</p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle>Take action</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <Textarea
            placeholder="Optional note for the patient or care team…"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          {error && (
            <div className="text-sm text-triage-red">{error}</div>
          )}
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => act("accept")} disabled={busy}>
              <CheckCircle2 className="h-4 w-4" /> Accept (telehealth)
            </Button>
            <Button variant="outline" onClick={() => act("reschedule")} disabled={busy}>
              <RotateCcw className="h-4 w-4" /> Reschedule
            </Button>
            <Button variant="destructive" onClick={() => act("reject")} disabled={busy}>
              <X className="h-4 w-4" /> Reject
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="space-y-2">
        <h3 className="font-display text-base font-semibold text-ink-DEFAULT">Reasoning trace</h3>
        {reasoning_traces?.length ? (
          <div className="space-y-2">
            {reasoning_traces.map((t: any) => (
              <AIInsightCard key={t.id || `${t.agent_name}-${t.timestamp}`} trace={t} />
            ))}
          </div>
        ) : (
          <EmptyState title="No reasoning traces yet" />
        )}
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: any }) {
  return (
    <div className="flex justify-between gap-2 border-b border-border py-1 text-sm last:border-0">
      <span className="text-ink-40">{k}</span>
      <span className="font-medium text-ink-DEFAULT">{v || "—"}</span>
    </div>
  );
}
