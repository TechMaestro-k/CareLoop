import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { CalendarClock, CheckCircle2, Clock, CreditCard, Video } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

type Slot = { iso: string; human: string; duration_min: number };
type Payment = {
  status: "pending" | "paid" | "failed" | "refunded";
  amount_usd: number;
  currency: string;
  link?: string;
  mock?: boolean;
};
type ChosenSlot = Slot & { payment?: Payment };
type Proposal = {
  id: string;
  proposed_slots: Slot[];
  chosen_slot: ChosenSlot | null;
  patient_status: string;
  doctor_status: string;
  jitsi_link: string | null;
  calendar_link: string | null;
};

export default function PatientBookingPage() {
  const { proposalId } = useParams<{ proposalId: string }>();
  const id = proposalId!;
  const [data, setData] = useState<{ proposal: Proposal; patient: any } | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState<string | null>(null);
  const [paying, setPaying] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    try {
      const d: any = await api.getProposal(id);
      setData(d);
    } catch (e: any) {
      setError(e?.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function pick(slotIso: string) {
    setSubmitting(slotIso);
    setError("");
    try {
      await api.selectSlot(id, slotIso);
      await load();
    } catch (e: any) {
      setError(e?.message || "Could not save your pick");
    } finally {
      setSubmitting(null);
    }
  }

  async function simulatePay() {
    setPaying(true);
    setError("");
    try {
      await api.simulateBookingPayment(id);
      await load();
    } catch (e: any) {
      setError(e?.message || "Payment simulation failed");
    } finally {
      setPaying(false);
    }
  }

  if (loading)
    return <div className="p-8 text-center text-sm text-ink-40">Loading your appointment…</div>;
  if (error && !data)
    return (
      <div className="p-6">
        <div className="rounded-xl border border-triage-red/30 bg-triage-redSoft p-4 text-sm text-triage-red">
          {error}
        </div>
      </div>
    );
  if (!data) return null;

  const { proposal: p, patient } = data;
  const accepted = p.doctor_status === "accepted";
  const chosen = p.patient_status === "chosen";
  const payment = p.chosen_slot?.payment;
  const paid = payment?.status === "paid";

  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight flex items-center gap-2">
          <CalendarClock className="h-5 w-5 text-mint-ink" />
          Pick a telehealth time
        </h1>
        <p className="mt-1 text-sm text-ink-60">
          {patient?.name ? `For ${patient.name}` : "Confidential booking link"} — choose any
          slot that works. The doctor confirms and we send the video link as soon as the
          consult fee is received.
        </p>
      </div>

      {accepted && p.chosen_slot && (
        <Card className="border-triage-green/40 bg-triage-greenSoft">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-triage-green text-lg">
              <CheckCircle2 className="h-5 w-5" /> Confirmed by doctor
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-ink-DEFAULT">
            <div className="text-base font-medium">{p.chosen_slot.human}</div>
            {p.jitsi_link && (
              <a
                href={p.jitsi_link}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-2 rounded-lg bg-triage-green px-4 py-2 text-sm font-medium text-white hover:bg-triage-green/90"
              >
                <Video className="h-4 w-4" /> Join video call
              </a>
            )}
            {p.calendar_link && (
              <div>
                <a
                  href={p.calendar_link}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sm text-ink-60 underline"
                >
                  Add to Google Calendar
                </a>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {chosen && !paid && p.chosen_slot && payment && (
        <Card className="border-mint-deep/40 bg-mint-soft">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-mint-ink text-lg">
              <CreditCard className="h-5 w-5" /> Confirm with payment
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-ink-DEFAULT">
            <div className="font-medium">{p.chosen_slot.human}</div>
            <div>
              Pay the <strong>${payment.amount_usd} {payment.currency}</strong> consult fee to
              hold this slot. The doctor will confirm only after payment is received.
            </div>
            {payment.link && (
              <a
                href={payment.link}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-2 rounded-lg bg-ink-DEFAULT px-4 py-2 text-sm font-medium text-white hover:bg-ink-80"
              >
                <CreditCard className="h-4 w-4" /> Pay ${payment.amount_usd} now
              </a>
            )}
            {payment.mock && (
              <div className="border-t border-mint/40 pt-3">
                <p className="mb-2 text-xs text-ink-40">
                  Test mode — payment gateway is sandboxed. Use the button below to mark
                  payment received instantly.
                </p>
                <Button onClick={simulatePay} disabled={paying} size="sm" variant="outline">
                  {paying ? "Marking paid…" : "Mark payment received (test mode)"}
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {chosen && paid && !accepted && p.chosen_slot && (
        <Card className="border-triage-amber/40 bg-triage-amberSoft">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-triage-amber text-lg">
              <Clock className="h-5 w-5" /> Payment received — waiting on doctor
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-ink-DEFAULT">
            <div className="font-medium">{p.chosen_slot.human}</div>
            <p className="mt-2 text-ink-60">
              The doctor has been notified. You'll get a WhatsApp with the video link as
              soon as it's confirmed.
            </p>
          </CardContent>
        </Card>
      )}

      {p.doctor_status === "rejected" && (
        <Card className="border-triage-red/30 bg-triage-redSoft">
          <CardContent className="p-4 text-sm text-triage-red">
            The doctor cannot make this slot. Please reply on WhatsApp and we'll share new
            times. Your payment will be refunded automatically.
          </CardContent>
        </Card>
      )}

      {!chosen && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-lg">Open slots</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {(p.proposed_slots || []).map((s) => (
              <button
                key={s.iso}
                onClick={() => pick(s.iso)}
                disabled={submitting !== null}
                className="flex w-full items-center justify-between gap-3 rounded-xl border border-border bg-surface p-4 text-left transition hover:bg-mint-soft disabled:opacity-50"
              >
                <div>
                  <div className="font-medium text-ink-DEFAULT">{s.human}</div>
                  <div className="text-xs text-ink-40">
                    {s.duration_min} min · video consult
                  </div>
                </div>
                <Badge className="border-border bg-muted text-ink-60">
                  {submitting === s.iso ? "Saving…" : "Pick"}
                </Badge>
              </button>
            ))}
            {error && (
              <div className="rounded-md bg-triage-redSoft p-3 text-sm text-triage-red">
                {error}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
