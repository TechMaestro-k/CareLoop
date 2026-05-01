import { useEffect, useState } from "react";
import { Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TriageBadge } from "@/components/TriageBadge";
import { api } from "@/lib/api";
import { formatTs, severityClass } from "@/lib/utils";

const SUGGESTED = [
  { label: "Greeting", text: "hi" },
  { label: "Feeling fine", text: "Doing okay today, took my morning meds." },
  { label: "Mild dyspnea", text: "I'm a bit short of breath today and my ankles are swollen." },
  { label: "Worsening", text: "I can barely breathe, can't lie flat at night, and I gained 3 kg this week." },
  { label: "Refill ask", text: "I've run out of metoprolol, can you arrange a refill?" },
];

type Bubble = {
  who: "patient" | "agent" | "system";
  text: string;
  severity?: string;
  ts: string;
  proposalId?: string;
  payment?: { proposalId: string; link?: string };
  acceptable?: { proposalId: string };
};

type EmailNotice = {
  to: string;
  address: string;
  subject: string;
  ok: boolean;
  mock: boolean;
  reason?: string;
  ts: string;
};

const PROPOSAL_RE = /\/(?:p\/)?booking\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i;
function extractProposalId(text: string): string | null {
  const m = text.match(PROPOSAL_RE);
  return m ? m[1] : null;
}

export function ChatPanel({
  patientId,
  patientName,
}: {
  patientId: string;
  patientName?: string;
}) {
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [emails, setEmails] = useState<EmailNotice[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [interactions, setInteractions] = useState<any[]>([]);
  const [slotCache, setSlotCache] = useState<Record<string, any[]>>({});

  async function refreshInteractions() {
    try {
      const data: any = await api.getPatient(patientId);
      setInteractions(data.interactions || []);
    } catch {}
  }

  useEffect(() => {
    void refreshInteractions();
    setBubbles([]);
    setEmails([]);
    setSlotCache({});
  }, [patientId]);

  function pushHandoff(w: any, ts: string) {
    setEmails((es) => [
      ...es,
      {
        to: w.to,
        address: w.phone,
        subject: `WhatsApp → ${w.to} (${w.mock ? "mock" : "live"})`,
        ok: w.ok,
        mock: w.mock,
        reason: w.reason,
        ts,
      },
    ]);
  }

  async function send(text: string) {
    if (!text.trim() || loading) return;
    setLoading(true);
    const ts = new Date().toISOString();
    setBubbles((h) => [...h, { who: "patient", text, ts }]);
    setDraft("");
    try {
      const res: any = await api.simulate(patientId, text);
      const sev = res?.classification?.severity;
      const wa: any[] = res?.whatsapp_sent || [];
      const em: any[] = res?.emails_sent || [];
      const replyTs = new Date().toISOString();

      const patientReplies = wa.filter((w: any) => w.to === "patient");
      if (patientReplies.length === 0) {
        setBubbles((h) => [
          ...h,
          { who: "agent", text: res.decision_summary || res.decision || "(no reply was sent)", severity: sev, ts: replyTs },
        ]);
      } else {
        setBubbles((h) => [
          ...h,
          ...patientReplies.map((w: any) => {
            const proposalId = extractProposalId(w.text || "") || undefined;
            return { who: "agent" as const, text: w.text, severity: sev, ts: replyTs, proposalId };
          }),
        ]);
        for (const w of patientReplies) {
          const pid = extractProposalId(w.text || "");
          if (pid && !slotCache[pid]) {
            api
              .getProposal(pid)
              .then((d: any) => {
                const slots = d?.proposal?.proposed_slots || [];
                setSlotCache((sc) => ({ ...sc, [pid]: slots }));
              })
              .catch(() => undefined);
          }
        }
      }

      wa.filter((w: any) => w.to !== "patient").forEach((w: any) => pushHandoff(w, replyTs));
      em.forEach((e: any) => setEmails((es) => [...es, { ...e, ts: replyTs }]));
      await refreshInteractions();
    } catch (e: any) {
      setBubbles((h) => [...h, { who: "agent", text: `Error: ${e.message}`, ts: new Date().toISOString() }]);
    } finally {
      setLoading(false);
    }
  }

  async function pickSlot(proposalId: string, slot: any) {
    if (loading) return;
    setLoading(true);
    const ts = new Date().toISOString();
    setBubbles((h) => [...h, { who: "patient", text: `I'll take ${slot.human}.`, ts }]);
    try {
      const res: any = await api.selectSlot(proposalId, slot.iso);
      const link = res?.payment?.link || "";
      const replyTs = new Date().toISOString();
      setBubbles((h) => [
        ...h,
        {
          who: "agent",
          text: link
            ? `Got it — ${slot.human}.\n\nPlease pay the consult fee to confirm:\n${link}`
            : `Got it — ${slot.human}. Payment link unavailable.`,
          ts: replyTs,
          payment: { proposalId, link },
        },
      ]);
      await refreshInteractions();
    } catch (e: any) {
      setBubbles((h) => [...h, { who: "agent", text: `Error: ${e.message}`, ts: new Date().toISOString() }]);
    } finally {
      setLoading(false);
    }
  }

  async function payNow(proposalId: string) {
    if (loading) return;
    setLoading(true);
    const ts = new Date().toISOString();
    setBubbles((h) => [...h, { who: "system", text: "Patient completed payment (test mode)", ts }]);
    try {
      const res: any = await api.simulateBookingPayment(proposalId);
      const replyTs = new Date().toISOString();
      setBubbles((h) => [
        ...h,
        {
          who: "agent",
          text: "Payment received — thank you. The doctor will confirm shortly and we'll send your video link.",
          ts: replyTs,
          acceptable: { proposalId },
        },
      ]);
      setEmails((es) => [
        ...es,
        {
          to: "doctor",
          address: "doctor@careloop",
          subject: "Paid booking notification",
          ok: !!res?.ok,
          mock: false,
          ts: replyTs,
        },
      ]);
      await refreshInteractions();
    } catch (e: any) {
      setBubbles((h) => [...h, { who: "agent", text: `Error: ${e.message}`, ts: new Date().toISOString() }]);
    } finally {
      setLoading(false);
    }
  }

  async function doctorAccept(proposalId: string) {
    if (loading) return;
    setLoading(true);
    const ts = new Date().toISOString();
    setBubbles((h) => [...h, { who: "system", text: "Doctor accepted the slot in their inbox", ts }]);
    try {
      const res: any = await api.decideProposal(proposalId, "accept");
      const replyTs = new Date().toISOString();
      const link = res?.booking?.link || "";
      const when = res?.booking?.slot_human || "";
      setBubbles((h) => [
        ...h,
        {
          who: "agent",
          text: link
            ? `Doctor confirmed your telehealth at ${when}.\nJoin from any browser: ${link}`
            : "Doctor confirmed.",
          ts: replyTs,
        },
      ]);
      setEmails((es) => [
        ...es,
        {
          to: "doctor",
          address: "doctor@careloop",
          subject: `Calendar booking added · ${when}`,
          ok: true,
          mock: false,
          ts: replyTs,
        },
      ]);
      await refreshInteractions();
    } catch (e: any) {
      setBubbles((h) => [...h, { who: "agent", text: `Error: ${e.message}`, ts: new Date().toISOString() }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Simulate WhatsApp from {patientName || "patient"}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {SUGGESTED.map((s) => (
              <Button
                key={s.label}
                variant="outline"
                size="sm"
                onClick={() => send(s.text)}
                disabled={loading}
              >
                {s.label}
              </Button>
            ))}
          </div>
          <div className="space-y-2 max-h-[520px] overflow-auto rounded-xl border border-border bg-muted/40 p-3">
            {bubbles.length === 0 && (
              <p className="py-8 text-center text-xs text-ink-40">
                Click a suggestion above or type a custom message to simulate inbound WhatsApp.
              </p>
            )}
            {bubbles.map((h, i) => {
              if (h.who === "system") {
                return (
                  <div key={i} className="flex justify-center">
                    <div className="px-2 py-1 text-[11px] italic text-ink-40">{h.text}</div>
                  </div>
                );
              }
              const slots = h.proposalId ? slotCache[h.proposalId] || [] : [];
              return (
                <div key={i} className={`flex ${h.who === "patient" ? "justify-end" : "justify-start"}`}>
                  <div
                    className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm whitespace-pre-wrap shadow-sm ${
                      h.who === "patient"
                        ? "bg-mint text-ink-DEFAULT"
                        : "bg-surface border border-border text-ink-DEFAULT"
                    }`}
                  >
                    <div>{h.text}</div>
                    {h.severity && h.who === "agent" && (
                      <div className="mt-1.5">
                        <TriageBadge severity={h.severity} />
                      </div>
                    )}
                    {h.proposalId && (
                      <div className="mt-2 flex flex-col gap-1">
                        <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-40">
                          Tap a slot
                        </div>
                        {slots.length === 0 && (
                          <div className="text-[11px] text-ink-40">Loading slots…</div>
                        )}
                        {slots.map((s: any) => (
                          <Button
                            key={s.iso}
                            size="sm"
                            variant="outline"
                            disabled={loading}
                            onClick={() => pickSlot(h.proposalId!, s)}
                            className="justify-start text-left h-auto py-1.5"
                          >
                            {s.human}
                          </Button>
                        ))}
                      </div>
                    )}
                    {h.payment && h.payment.link && (
                      <div className="mt-2 flex flex-col gap-1.5">
                        <a
                          href={h.payment.link}
                          target="_blank"
                          rel="noreferrer"
                          className="break-all text-[12px] underline text-ink-60"
                        >
                          {h.payment.link}
                        </a>
                        <Button size="sm" disabled={loading} onClick={() => payNow(h.payment!.proposalId)}>
                          Pay consult fee (test mode)
                        </Button>
                      </div>
                    )}
                    {h.acceptable && (
                      <div className="mt-2">
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={loading}
                          onClick={() => doctorAccept(h.acceptable!.proposalId)}
                        >
                          Doctor accepts (simulate)
                        </Button>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
            {emails.length > 0 && (
              <div className="mt-3 space-y-1 border-t border-border pt-2">
                <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-40">
                  Notifications sent
                </div>
                {emails.slice(-8).map((e, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between gap-2 rounded-md border border-border bg-surface px-2 py-1 text-[11px]"
                  >
                    <span className="text-ink-40">
                      <strong className="text-ink-DEFAULT">{e.to}</strong> · {e.address}
                    </span>
                    <span className="truncate text-ink-40">{e.subject}</span>
                    <Badge
                      className={
                        e.ok === false
                          ? "border-triage-red/40 bg-triage-redSoft text-triage-red"
                          : e.mock
                          ? "border-border bg-muted text-ink-40"
                          : "border-mint bg-mint-soft text-mint-ink"
                      }
                    >
                      {e.ok === false ? "failed" : e.mock ? "mock" : "sent"}
                    </Badge>
                    {e.ok === false && e.reason && (
                      <span className="text-[10px] text-triage-red" title={e.reason}>
                        {e.reason.length > 40 ? e.reason.slice(0, 40) + "…" : e.reason}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="flex gap-2">
            <Input
              placeholder="Type a message as the patient…"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void send(draft);
              }}
              disabled={loading}
            />
            <Button onClick={() => send(draft)} disabled={loading || !draft.trim()}>
              <Send className="h-4 w-4" />
              Send
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Recent interactions (database)</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2 max-h-[600px] overflow-auto">
            {interactions.length === 0 && (
              <p className="text-xs text-ink-40">No interactions yet.</p>
            )}
            {interactions.map((it: any) => (
              <div key={it.id} className="rounded-lg border border-border bg-surface p-2 text-xs">
                <div className="flex items-center justify-between">
                  <Badge className={severityClass(it.classification)}>
                    {it.direction} · {it.classification || "—"}
                  </Badge>
                  <span className="text-ink-40">{formatTs(it.timestamp)}</span>
                </div>
                <p className="mt-1 whitespace-pre-wrap text-ink-DEFAULT">{it.content}</p>
                {it.agent_decision && (
                  <p className="mt-1 text-mint-ink">→ {it.agent_decision}</p>
                )}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
