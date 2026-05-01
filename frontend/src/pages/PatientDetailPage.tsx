import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { TriageBadge } from "@/components/TriageBadge";
import { KGViewer } from "@/components/KGViewer";
import { AIInsightCard } from "@/components/AIInsightCard";
import { ChatPanel } from "@/components/ChatPanel";
import { EmptyState } from "@/components/EmptyState";
import { api } from "@/lib/api";
import { formatTs, severityClass, initials } from "@/lib/utils";
import { ArrowLeft, RefreshCw, Activity, FileText, Network, Sparkles, MessageSquare } from "lucide-react";

export default function PatientDetailPage() {
  const params = useParams<{ patientId: string }>();
  const id = params.patientId!;
  const [data, setData] = useState<any>(null);
  const [traces, setTraces] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function reload() {
    setLoading(true);
    setError(null);
    try {
      const [d, t]: any[] = await Promise.all([api.getPatient(id), api.patientReasoning(id, 50)]);
      setData(d);
      setTraces(t.traces || []);
    } catch (e: any) {
      setError(e.message || "Failed to load patient");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (loading && !data) return <div className="text-sm text-ink-40">Loading patient…</div>;
  if (error) return <div className="card-base border-triage-red/30 bg-triage-redSoft p-4 text-sm text-triage-red">{error}</div>;
  if (!data) return null;

  const {
    patient,
    clinical,
    sdoh,
    knowledge_graph,
    care_plans,
    interactions,
    medications_inventory,
    escalations,
  } = data;
  const latestPlan = care_plans?.[0]?.plan_json || {};
  const latestSeverity =
    interactions?.find((i: any) => i.classification)?.classification || "green";
  const openEscalations = (escalations || []).filter((e: any) => e.status === "pending").length;

  return (
    <div className="space-y-6">
      <div>
        <Link to="/patients" className="inline-flex items-center gap-1 text-sm text-ink-40 hover:text-ink-DEFAULT">
          <ArrowLeft className="h-3.5 w-3.5" />
          All patients
        </Link>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-mint-soft font-display text-base font-semibold text-mint-ink">
              {initials(patient.name)}
            </div>
            <div>
              <h2 className="font-display text-2xl font-bold tracking-tight">
                {patient.name}{" "}
                <span className="ml-1 text-sm font-normal text-ink-40">· {patient.age}y</span>
              </h2>
              <p className="text-sm text-ink-60">{clinical?.diagnosis || "Awaiting clinical extraction"}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <TriageBadge severity={latestSeverity} />
            <Button variant="outline" onClick={reload} size="sm">
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh
            </Button>
          </div>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Risk score"
          value={
            patient.risk_score != null
              ? `${(patient.risk_score * 100).toFixed(0)}%`
              : (traces.find((t: any) => t.inferred?.risk_score != null)?.inferred?.risk_score != null
                  ? `${(traces.find((t: any) => t.inferred?.risk_score != null)!.inferred.risk_score * 100).toFixed(0)}%`
                  : "—")
          }
          tone={
            patient.risk_score != null
              ? patient.risk_score >= 0.7
                ? "red"
                : patient.risk_score >= 0.45
                  ? "amber"
                  : "green"
              : undefined
          }
        />
        <Stat label="Channel" value={latestPlan.channel || patient.channel_pref || "—"} />
        <Stat
          label="Check-ins / day"
          value={`${latestPlan.check_in_times_per_day || 3}× · from ${latestPlan.check_in_time || "09:00"}`}
        />
        <Stat label="Open escalations" value={String(openEscalations)} tone={openEscalations > 0 ? "red" : "green"} />
      </div>

      <Tabs defaultValue="overview">
        <TabsList className="flex flex-wrap">
          <TabsTrigger value="overview"><FileText className="mr-1 h-3.5 w-3.5" />Overview</TabsTrigger>
          <TabsTrigger value="plan"><Activity className="mr-1 h-3.5 w-3.5" />Care plan</TabsTrigger>
          <TabsTrigger value="reasoning"><Sparkles className="mr-1 h-3.5 w-3.5" />AI reasoning</TabsTrigger>
          <TabsTrigger value="kg"><Network className="mr-1 h-3.5 w-3.5" />Knowledge graph</TabsTrigger>
          <TabsTrigger value="chat"><MessageSquare className="mr-1 h-3.5 w-3.5" />Chat</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader><CardTitle>Clinical</CardTitle></CardHeader>
              <CardContent className="space-y-2 text-sm">
                <Row k="Diagnosis" v={clinical?.diagnosis} />
                <Row k="Comorbidities" v={(clinical?.comorbidities || []).join(", ")} />
                <Row k="Discharge date" v={clinical?.discharge_date} />
                <Row k="Follow-up" v={clinical?.follow_up_date} />
                <div className="pt-2">
                  <div className="mb-1 text-xs font-semibold uppercase text-ink-40">Medications</div>
                  {(clinical?.medications || []).length === 0 ? (
                    <p className="text-sm text-ink-40">None recorded.</p>
                  ) : (
                    <ul className="list-disc space-y-0.5 pl-5 text-sm text-ink-DEFAULT">
                      {(clinical?.medications || []).map((m: any, i: number) => (
                        <li key={i}>
                          {m.name || m}
                          {m.dose ? ` · ${m.dose}` : ""}
                          {m.frequency ? ` · ${m.frequency}` : ""}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Social context (SDOH)</CardTitle></CardHeader>
              <CardContent className="space-y-2 text-sm">
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
                  <p className="text-sm text-ink-40">No SDOH profile yet.</p>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Medication inventory</CardTitle></CardHeader>
              <CardContent>
                {medications_inventory?.length ? (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-left text-xs font-semibold uppercase text-ink-40">
                          <th className="py-2">Medication</th>
                          <th>Days remaining</th>
                          <th>Last refill</th>
                        </tr>
                      </thead>
                      <tbody>
                        {medications_inventory.map((m: any) => (
                          <tr key={m.id} className="border-t border-border">
                            <td className="py-2">{m.med_name}</td>
                            <td>{m.days_remaining ?? m.count_remaining}</td>
                            <td>{m.last_refill_date}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="text-sm text-ink-40">No inventory data.</p>
                )}
              </CardContent>
            </Card>
            <Card className="lg:col-span-1">
              <CardHeader><CardTitle>Recent interactions</CardTitle></CardHeader>
              <CardContent>
                {interactions?.length ? (
                  <div className="space-y-2 max-h-80 overflow-auto pr-1">
                    {interactions.map((it: any) => (
                      <div key={it.id} className="rounded-lg border border-border bg-surface p-2 text-xs">
                        <div className="flex items-center justify-between">
                          <Badge className={severityClass(it.classification)}>
                            {it.direction} · {it.classification || "—"}
                          </Badge>
                          <span className="text-ink-40">{formatTs(it.timestamp)}</span>
                        </div>
                        <p className="mt-1 text-ink-DEFAULT">{it.content}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyState title="No interactions yet" description="They'll appear once the patient replies." />
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="plan">
          <CarePlanView plan={latestPlan} />
        </TabsContent>

        <TabsContent value="reasoning" className="space-y-3">
          {traces.length === 0 ? (
            <EmptyState title="No reasoning traces yet" description="Run an interaction to see how the agents think." />
          ) : (
            traces.map((t) => <AIInsightCard key={t.id || `${t.agent_name}-${t.timestamp}`} trace={t} />)
          )}
        </TabsContent>

        <TabsContent value="kg">
          <Card>
            <CardHeader>
              <CardTitle>Per-patient knowledge graph</CardTitle>
              <CardDescription>Diagnosis · medications · SDOH · red flags · routing.</CardDescription>
            </CardHeader>
            <CardContent>
              <KGViewer data={knowledge_graph} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="chat">
          <ChatPanel patientId={id} patientName={patient.name} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function CarePlanView({ plan }: { plan: any }) {
  if (!plan || Object.keys(plan).length === 0) {
    return <EmptyState title="Care plan not generated yet" description="Onboarding triggers the plan automatically." />;
  }
  const goals: string[] = Array.isArray(plan.goals) ? plan.goals : [];
  const checks: any[] = Array.isArray(plan.daily_checks) ? plan.daily_checks : [];
  const redFlags: string[] = Array.isArray(plan.red_flags) ? plan.red_flags : [];
  const checkInTime = plan.check_in_time || "09:00";
  const cadence = plan.check_in_cadence || "daily";
  const channel = plan.channel || "whatsapp_text";

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Cadence & channel</CardTitle>
          <CardDescription>How and when CareLoop reaches the patient.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <Row k="Channel" v={channel} />
          <Row k="Cadence" v={cadence} />
          <Row k="Check-in time" v={checkInTime} />
          {plan.language && <Row k="Language" v={plan.language} />}
        </CardContent>
      </Card>
      {goals.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Goals</CardTitle></CardHeader>
          <CardContent>
            <ul className="list-disc space-y-1 pl-5 text-sm text-ink-DEFAULT">
              {goals.map((g, i) => <li key={i}>{g}</li>)}
            </ul>
          </CardContent>
        </Card>
      )}
      {checks.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Daily checks</CardTitle></CardHeader>
          <CardContent>
            <ul className="list-disc space-y-1 pl-5 text-sm text-ink-DEFAULT">
              {checks.map((c, i) => (
                <li key={i}>{typeof c === "string" ? c : c.question || c.label}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
      {redFlags.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Red flags to watch</CardTitle></CardHeader>
          <CardContent>
            <ul className="list-disc space-y-1 pl-5 text-sm text-triage-red">
              {redFlags.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Row({ k, v }: { k: string; v: any }) {
  return (
    <div className="flex justify-between gap-2 border-b border-border py-1.5 last:border-0">
      <span className="text-ink-40">{k}</span>
      <span className="text-right font-medium text-ink-DEFAULT">{v || "—"}</span>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "red" | "amber" | "green" }) {
  const toneClass =
    tone === "red" ? "text-triage-red" :
    tone === "amber" ? "text-triage-amber" :
    tone === "green" ? "text-triage-green" :
    "text-ink-DEFAULT";
  return (
    <Card>
      <CardContent className="p-4">
        <div className="text-xs font-medium uppercase tracking-wide text-ink-40">{label}</div>
        <div className={`mt-1 font-display text-2xl font-bold ${toneClass}`}>{value}</div>
      </CardContent>
    </Card>
  );
}
