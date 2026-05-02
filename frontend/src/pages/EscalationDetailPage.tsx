import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, CalendarClock } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TriageBadge } from "@/components/TriageBadge";
import { api } from "@/lib/api";
import { formatTs, severityClass, triageBarClass } from "@/lib/utils";

export default function EscalationDetailPage() {
  const params = useParams<{ escId: string }>();
  const id = params.escId!;
  const [data, setData] = useState<any>(null);
  const [proposal, setProposal] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const d = await api.getEscalation(id);
      setData(d);
      // find the most recent non-completed proposal for this patient
      const pid = d.patient?.id || d.escalation?.patient_id;
      if (pid) {
        const pr = await api.listProposals({});
        const relevant = (pr.proposals || [])
          .filter(
            (p: any) =>
              (p.patient_id === pid || p.patient?.id === pid) &&
              p.doctor_status !== "completed",
          )
          .sort((a: any, b: any) =>
            (b.created_at || "").localeCompare(a.created_at || ""),
          );
        if (relevant.length > 0) setProposal(relevant[0]);
      }
    } catch (e: any) {
      setError(e?.message || "Failed to load");
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (error && !data) {
    return (
      <div className="card-base border-triage-red/30 bg-triage-redSoft p-3 text-sm text-triage-red">
        {error}
      </div>
    );
  }
  if (!data) return <p className="text-sm text-ink-40">Loading…</p>;
  const { escalation, patient, clinical, sdoh, interactions } = data;

  return (
    <div className="space-y-5">
      <Link
        to="/doctor/inbox"
        className="inline-flex items-center gap-1 text-sm text-ink-40 hover:text-ink-DEFAULT"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> Back to inbox
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

      {/* Booking proposal action strip */}
      {proposal ? (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-mint/40 bg-mint-soft/60 px-4 py-3">
          <CalendarClock className="h-4 w-4 text-mint-ink flex-shrink-0" />
          <div className="flex-1 text-sm text-mint-ink">
            {proposal.patient_status === "pending"
              ? "A slot-selection link has been sent to the patient. You'll be notified once they pick and pay."
              : proposal.patient_status === "chosen" &&
                  proposal.doctor_status === "pending"
                ? "The patient has selected a slot. Go to the inbox to review the AI summary and confirm."
                : proposal.doctor_status === "accepted"
                  ? "This booking is confirmed. Join the call from the inbox."
                  : "Booking proposal exists — view it below."}
          </div>
          <Button asChild size="sm">
            <Link
              to={
                proposal.doctor_status === "pending" ||
                proposal.doctor_status === "accepted"
                  ? "/doctor/inbox"
                  : `/p/booking/${proposal.id}`
              }
            >
              {proposal.patient_status === "chosen" && proposal.doctor_status === "pending"
                ? "Go to inbox →"
                : "View booking"}
            </Link>
          </Button>
        </div>
      ) : (
        <div className="rounded-xl border border-triage-amber/30 bg-triage-amberSoft px-4 py-3 text-sm text-triage-amber">
          No booking proposal yet. The agent will send the patient a slot-selection link
          automatically when a RED escalation is triggered.
        </div>
      )}

      {/* Agent brief */}
      <Card className={triageBarClass(escalation.severity)}>
        <CardHeader>
          <CardTitle>Agent brief</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="whitespace-pre-wrap rounded-lg bg-muted p-3 text-sm text-ink-DEFAULT">
            {escalation.brief}
          </pre>
        </CardContent>
      </Card>

      <div className="grid gap-3 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>SDOH context</CardTitle>
          </CardHeader>
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
          <CardHeader>
            <CardTitle>Recent interactions</CardTitle>
          </CardHeader>
          <CardContent>
            {interactions?.length ? (
              <div className="max-h-72 space-y-2 overflow-auto pr-1">
                {interactions.map((it: any) => (
                  <div
                    key={it.id}
                    className="rounded-lg border border-border bg-surface p-2 text-xs"
                  >
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
