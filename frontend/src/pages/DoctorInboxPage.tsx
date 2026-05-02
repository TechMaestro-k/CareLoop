import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  CalendarDays,
  CheckCircle2,
  Clock,
  Flag,
  RefreshCw,
  Sparkles,
  Video,
  X,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TriageBadge } from "@/components/TriageBadge";
import { EmptyState } from "@/components/EmptyState";
import { api } from "@/lib/api";
import { formatTs, triageBarClass } from "@/lib/utils";

type Proposal = any;
type Escalation = any;
type HandoffSummary = {
  summary?: string;
  symptoms_reported?: string[];
  medication_adherence?: string;
  risk_signals?: string[];
  sdoh_context?: string[];
  agent_actions_so_far?: string[];
  doctor_focus?: string[];
};

export default function DoctorInboxPage() {
  const [items, setItems] = useState<Proposal[]>([]);
  const [escalations, setEscalations] = useState<Escalation[]>([]);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [summaries, setSummaries] = useState<Record<string, HandoffSummary | "loading" | "error">>({});

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [r, e] = await Promise.all([
        api.listProposals({}),
        api.listEscalations("pending"),
      ]);
      setItems(r.proposals || []);
      setEscalations(e.escalations || []);
    } catch (e: any) {
      setError(e?.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  // ── derived lists ──────────────────────────────────────────────
  // Proposals where patient picked a slot and doctor hasn't decided yet
  const awaitingDecision = useMemo(
    () =>
      items.filter(
        (i) => i.patient_status === "chosen" && i.doctor_status === "pending",
      ),
    [items],
  );

  // Accepted but not yet completed
  const confirmed = useMemo(
    () => items.filter((i) => i.doctor_status === "accepted"),
    [items],
  );

  // Waiting for patient to pick
  const awaitingPatient = useMemo(
    () =>
      items.filter(
        (i) =>
          i.patient_status === "pending" && i.doctor_status === "pending",
      ),
    [items],
  );

  // Map patient_id → latest non-completed proposal so escalation "Open" links to booking
  const proposalByPatient = useMemo(() => {
    const m = new Map<string, Proposal>();
    for (const p of items) {
      if (p.doctor_status === "completed") continue;
      const pid = p.patient_id || p.patient?.id;
      if (!pid) continue;
      const existing = m.get(pid);
      if (!existing || (p.created_at || "") > (existing.created_at || "")) {
        m.set(pid, p);
      }
    }
    return m;
  }, [items]);

  function escalationDeeplink(e: Escalation): string {
    const pid = e.patient_id || e.patient?.id;
    const p = pid ? proposalByPatient.get(pid) : null;
    if (p?.id) return `/p/booking/${p.id}`;
    return `/doctor/escalations/${e.id}`;
  }

  // ── load handoff summaries for awaiting-decision cards ─────────
  useEffect(() => {
    const missing = awaitingDecision.filter(
      (p) => !p.doctor_handoff_summary && !summaries[p.id],
    );
    if (missing.length === 0) return;
    let cancelled = false;
    setSummaries((s) => {
      const next = { ...s };
      for (const p of missing) next[p.id] = "loading";
      return next;
    });
    (async () => {
      for (const p of missing) {
        try {
          const res: any = await api.getProposal(p.id);
          if (cancelled) return;
          const summary =
            res?.doctor_handoff_summary ||
            res?.proposal?.doctor_handoff_summary ||
            null;
          setSummaries((s) => ({ ...s, [p.id]: summary || "error" }));
        } catch {
          if (cancelled) return;
          setSummaries((s) => ({ ...s, [p.id]: "error" }));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [awaitingDecision.map((p) => p.id).join(",")]);

  function summaryFor(p: Proposal): HandoffSummary | "loading" | "error" | null {
    if (p.doctor_handoff_summary && typeof p.doctor_handoff_summary === "object") {
      return p.doctor_handoff_summary as HandoffSummary;
    }
    return summaries[p.id] ?? null;
  }

  // ── actions ────────────────────────────────────────────────────
  async function decide(id: string, action: "accept" | "reject") {
    setWorking(`${id}:${action}`);
    setError("");
    try {
      await api.decideProposal(id, action);
      await load();
    } catch (e: any) {
      const body = (e as any)?.body;
      if (typeof body === "object" && body?.detail?.message) {
        setError(`${body.detail.message} ${body.detail.hint || ""}`);
      } else {
        setError(e?.message || "Action failed");
      }
    } finally {
      setWorking(null);
    }
  }

  async function markPaymentReceived(id: string) {
    setWorking(`${id}:pay`);
    setError("");
    try {
      await api.markBookingPaid(id);
      await load();
    } catch (e: any) {
      setError(e?.message || "Payment update failed");
    } finally {
      setWorking(null);
    }
  }

  async function markCompleted(id: string) {
    setWorking(`${id}:complete`);
    setError("");
    try {
      await api.completeProposal(id);
      await load();
    } catch (e: any) {
      setError(e?.message || "Could not mark completed");
    } finally {
      setWorking(null);
    }
  }

  // ── render ─────────────────────────────────────────────────────
  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="font-display text-2xl font-bold tracking-tight">Doctor inbox</h2>
          <p className="text-sm text-ink-40">
            AI escalations, slot picks awaiting your decision, and confirmed bookings.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
        </Button>
      </header>

      {error && (
        <div className="card-base border-triage-red/30 bg-triage-redSoft p-3 text-sm text-triage-red">
          {error}
        </div>
      )}
      {loading && <div className="text-sm text-ink-40">Loading…</div>}

      {/* ── 1. Recent escalations from agent ── */}
      <Section
        title="Recent escalations"
        empty="No pending escalations from the agent."
        icon={<AlertTriangle className="h-4 w-4 text-triage-red" />}
      >
        {escalations.map((e) => (
          <Card key={e.id} className={`bg-surface ${triageBarClass(e.severity)}`}>
            <CardHeader className="pb-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <CardTitle>
                  {e.patient?.name || "Patient"}{" "}
                  <span className="text-sm font-normal text-ink-40">
                    {e.patient?.age ? `· ${e.patient.age}y ` : ""}· {e.patient?.phone}
                  </span>
                </CardTitle>
                <div className="flex items-center gap-2">
                  <TriageBadge severity={e.severity} />
                  <span className="text-xs text-ink-40">{formatTs(e.created_at)}</span>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <pre className="whitespace-pre-wrap rounded-lg bg-muted p-3 text-xs text-ink-DEFAULT">
                {e.brief}
              </pre>
              <div className="rounded-lg border border-mint/30 bg-mint-soft/50 px-3 py-2 text-xs text-mint-ink">
                The agent has sent the patient a slot-selection link. Once the patient picks a
                slot and pays, it will appear below under "Awaiting your decision".
              </div>
              <div className="flex flex-wrap gap-2">
                <Button asChild size="sm" variant="outline">
                  <Link to={`/doctor/escalations/${e.id}`}>View full brief</Link>
                </Button>
                {proposalByPatient.get(e.patient_id || e.patient?.id) && (
                  <Button asChild size="sm">
                    <Link to={`/p/booking/${proposalByPatient.get(e.patient_id || e.patient?.id)!.id}`}>
                      Open booking proposal
                    </Link>
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
      </Section>

      {/* ── 2. Patient picked a slot — awaiting doctor decision ── */}
      <Section
        title="Awaiting your decision"
        empty="No patient picks waiting on you right now."
        icon={<Clock className="h-4 w-4 text-triage-amber" />}
      >
        {awaitingDecision.map((p) => {
          const payStatus = p.chosen_slot?.payment?.status || "pending";
          const isPaid = payStatus === "paid";
          const isMock = !!p.chosen_slot?.payment?.mock;
          const currency: string = p.chosen_slot?.payment?.currency || "INR";
          const amount: number = p.chosen_slot?.payment?.amount_usd ?? 0;
          const fmt = currency === "INR" ? `₹${amount}` : `${amount} ${currency}`;

          return (
            <Card key={p.id} className="triage-bar-amber">
              <CardHeader className="pb-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <CardTitle>
                    {p.patient?.name || "Patient"}{" "}
                    <span className="text-sm font-normal text-ink-40">
                      {p.patient?.age ? `· ${p.patient.age}y ` : ""}· {p.patient?.phone}
                    </span>
                  </CardTitle>
                  <div className="flex items-center gap-2">
                    <Badge className="border-triage-amber/40 bg-triage-amberSoft text-triage-amber">
                      Slot picked
                    </Badge>
                    <Badge
                      className={
                        isPaid
                          ? "border-triage-green/40 bg-triage-greenSoft text-triage-green"
                          : "border-triage-red/40 bg-triage-redSoft text-triage-red"
                      }
                    >
                      {isPaid ? "Paid" : "Payment pending"}
                    </Badge>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="text-sm">
                  <span className="text-ink-40">Chosen slot: </span>
                  <span className="font-medium text-ink-DEFAULT">
                    {p.chosen_slot?.human || "—"}
                  </span>
                </div>

                {!isPaid && (
                  <div className="rounded-lg border border-triage-amber/30 bg-triage-amberSoft px-3 py-2 text-xs text-triage-amber">
                    Patient has not yet paid the {fmt} consult fee.
                    {isMock
                      ? " Payment gateway is in test mode — mark received after verification."
                      : " They will receive a Razorpay link automatically."}
                  </div>
                )}

                <HandoffSummaryBlock state={summaryFor(p)} />

                <div className="flex flex-wrap gap-2">
                  {!isPaid && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => markPaymentReceived(p.id)}
                      disabled={working !== null}
                    >
                      {working === `${p.id}:pay` ? "Processing…" : "Mark payment received"}
                    </Button>
                  )}
                  <Button
                    size="sm"
                    onClick={() => decide(p.id, "accept")}
                    disabled={working !== null || !isPaid}
                    title={!isPaid ? "Patient must pay first" : "Confirm this booking"}
                  >
                    <CheckCircle2 className="h-4 w-4" />
                    {working === `${p.id}:accept` ? "Confirming…" : "Accept & send video link"}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => decide(p.id, "reject")}
                    disabled={working !== null}
                  >
                    <X className="h-4 w-4" />
                    {working === `${p.id}:reject` ? "Working…" : "Reject"}
                  </Button>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </Section>

      {/* ── 3. Confirmed bookings (accepted, not yet completed) ── */}
      <Section
        title="Confirmed bookings"
        empty="No confirmed bookings."
        icon={<CheckCircle2 className="h-4 w-4 text-triage-green" />}
      >
        {confirmed.map((p) => (
          <Card key={p.id} className="triage-bar-green">
            <CardHeader className="pb-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <CardTitle>
                  {p.patient?.name || "Patient"}{" "}
                  <span className="text-sm font-normal text-ink-40">
                    {p.patient?.age ? `· ${p.patient.age}y ` : ""}· {p.patient?.phone}
                  </span>
                </CardTitle>
                <Badge className="border-triage-green/40 bg-triage-greenSoft text-triage-green">
                  Confirmed
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="text-sm font-medium text-ink-DEFAULT">
                {p.chosen_slot?.human || "—"}
              </div>
              <div className="flex flex-wrap gap-2">
                {p.jitsi_link && (
                  <a
                    href={p.jitsi_link}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-2 rounded-lg bg-ink-DEFAULT px-3 py-1.5 text-sm font-medium text-white hover:bg-ink-80"
                  >
                    <Video className="h-3.5 w-3.5" /> Join video call
                  </a>
                )}
                {p.calendar_link && (
                  <a
                    href={p.calendar_link}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center rounded-lg border border-border bg-surface px-3 py-1.5 text-sm font-medium text-ink-DEFAULT hover:bg-mint-soft"
                  >
                    Add to calendar
                  </a>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  className="border-triage-green/40 text-triage-green hover:bg-triage-greenSoft"
                  onClick={() => markCompleted(p.id)}
                  disabled={working !== null}
                >
                  <Flag className="h-3.5 w-3.5" />
                  {working === `${p.id}:complete` ? "Marking…" : "Mark as completed"}
                </Button>
              </div>
              <div className="text-xs text-ink-40">
                Confirmed {formatTs(p.doctor_decided_at || p.created_at)}
              </div>
            </CardContent>
          </Card>
        ))}
      </Section>

      {/* ── 4. Waiting for patient to pick a slot ── */}
      <Section
        title="Awaiting patient response"
        empty="No proposals waiting on a patient."
        icon={<CalendarDays className="h-4 w-4 text-ink-40" />}
      >
        {awaitingPatient.map((p) => (
          <Card key={p.id}>
            <CardHeader className="pb-2">
              <CardTitle>
                {p.patient?.name || "Patient"}{" "}
                <span className="text-sm font-normal text-ink-40">· {p.patient?.phone}</span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="mb-2 text-xs text-ink-40">
                Sent {formatTs(p.created_at)} · {(p.proposed_slots || []).length} slots offered
              </div>
              <div className="space-y-0.5 text-xs text-ink-60">
                {(p.proposed_slots || []).map((s: any) => (
                  <div key={s.iso}>• {s.human}</div>
                ))}
              </div>
              <div className="mt-3">
                <Button asChild size="sm" variant="outline">
                  <Link to={`/p/booking/${p.id}`}>View booking page</Link>
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </Section>
    </div>
  );
}

function Section({
  title,
  empty,
  icon,
  children,
}: {
  title: string;
  empty: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  const arr = Array.isArray(children) ? children.flat() : children;
  const isEmpty = Array.isArray(arr) ? arr.length === 0 : !arr;
  return (
    <section className="space-y-2">
      <h3 className="flex items-center gap-2 font-display text-base font-semibold text-ink-DEFAULT">
        {icon}
        {title}
      </h3>
      {isEmpty ? (
        <EmptyState title={empty} />
      ) : (
        <div className="space-y-2">{children}</div>
      )}
    </section>
  );
}

function HandoffSummaryBlock({
  state,
}: {
  state: HandoffSummary | "loading" | "error" | null;
}) {
  if (state === null) return null;

  const wrapperClass =
    "rounded-lg border border-mint/40 bg-mint-soft/60 p-3 space-y-2 text-sm";
  const headerClass =
    "flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-mint-ink";

  if (state === "loading") {
    return (
      <div className={wrapperClass}>
        <div className={headerClass}>
          <Sparkles className="h-3.5 w-3.5" /> AI handoff summary
        </div>
        <div className="text-xs text-ink-40">Generating summary…</div>
      </div>
    );
  }
  if (state === "error") {
    return (
      <div className={wrapperClass}>
        <div className={headerClass}>
          <Sparkles className="h-3.5 w-3.5" /> AI handoff summary
        </div>
        <div className="text-xs text-triage-red">
          Could not load summary — review the patient record manually.
        </div>
      </div>
    );
  }

  const s = state;
  const list = (label: string, items?: string[]) => {
    if (!items || items.length === 0) return null;
    return (
      <div>
        <div className="text-xs font-medium text-mint-ink">{label}</div>
        <ul className="list-disc space-y-0.5 pl-5 text-xs text-ink-60">
          {items.map((it, i) => (
            <li key={i}>{it}</li>
          ))}
        </ul>
      </div>
    );
  };

  return (
    <div className={wrapperClass}>
      <div className={headerClass}>
        <Sparkles className="h-3.5 w-3.5" /> AI handoff summary
      </div>
      {s.summary && <p className="text-sm text-ink-DEFAULT">{s.summary}</p>}
      <div className="grid grid-cols-1 gap-x-4 gap-y-2 sm:grid-cols-2">
        {list("Symptoms reported", s.symptoms_reported)}
        <div>
          <div className="text-xs font-medium text-mint-ink">Medication adherence</div>
          <div className="text-xs text-ink-60">{s.medication_adherence || "unknown"}</div>
        </div>
        {list("Risk signals", s.risk_signals)}
        {list("SDOH context", s.sdoh_context)}
        {list("Agent actions so far", s.agent_actions_so_far)}
        {list("Doctor focus", s.doctor_focus)}
      </div>
      <div className="text-[10px] italic text-ink-40">
        AI-generated from the patient's recent CareLoop history. Not a diagnosis.
      </div>
    </div>
  );
}
