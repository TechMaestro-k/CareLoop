import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { DischargeForm, DEFAULT_PATIENT_FORM, type PatientForm } from "@/components/forms/DischargeForm";
import { SDOHForm } from "@/components/forms/SDOHForm";
import { api, ApiError } from "@/lib/api";
import { CheckCircle2, AlertCircle, ArrowRight } from "lucide-react";

const SDOH_REQUIRED_COUNT = 3;

function sdohFilledCount(sdoh: Record<string, string>): number {
  return Object.values(sdoh).filter((v) => v.trim().length > 0).length;
}

export default function OnboardPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState<"discharge" | "sdoh">("discharge");
  const [patient, setPatient] = useState<PatientForm>(DEFAULT_PATIENT_FORM);
  const [sdoh, setSdoh] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState<{ patient_id: string; risk_score?: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [duplicate, setDuplicate] = useState<{ id: string; name: string; phone: string } | null>(null);

  const dischargeValid = Boolean(patient.name.trim() && patient.phone.trim());
  const sdohFilled = sdohFilledCount(sdoh);
  const sdohReady = sdohFilled >= SDOH_REQUIRED_COUNT;
  const canSubmit = dischargeValid && sdohReady;

  async function submit() {
    setSubmitting(true);
    setError(null);
    setDuplicate(null);
    setSuccess(null);
    try {
      const res: any = await api.onboard({
        ...patient,
        age: Number(patient.age) || 0,
        sdoh_responses: sdoh,
      });
      setSuccess({ patient_id: res.patient_id, risk_score: res.risk_score });
      setTimeout(() => navigate(`/patients/${res.patient_id}`), 1200);
    } catch (e: any) {
      if (e instanceof ApiError && e.status === 409 && e.body?.detail?.error === "duplicate_patient") {
        const d = e.body.detail;
        setDuplicate({ id: d.existing_patient_id, name: d.existing_name, phone: d.existing_phone });
      } else {
        setError(e.message);
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h2 className="font-display text-2xl font-bold tracking-tight">Onboard a patient</h2>
        <p className="mt-1 text-sm text-ink-40">
          Capture the discharge summary and social context. Care plan, engagement and follow-up
          scheduling start automatically once you submit.
        </p>
      </header>

      {/* Step indicator */}
      <div className="flex items-center gap-3 text-sm">
        <button
          className={`flex items-center gap-1.5 font-medium transition ${step === "discharge" ? "text-mint-deep" : "text-ink-40 hover:text-ink-DEFAULT"}`}
          onClick={() => setStep("discharge")}
        >
          <span className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold ${step === "discharge" ? "bg-mint-deep text-white" : dischargeValid ? "bg-triage-greenSoft text-triage-green" : "bg-muted text-ink-40"}`}>
            {dischargeValid ? "✓" : "1"}
          </span>
          Discharge
        </button>
        <ArrowRight className="h-3.5 w-3.5 text-ink-20" />
        <button
          className={`flex items-center gap-1.5 font-medium transition ${step === "sdoh" ? "text-mint-deep" : "text-ink-40 hover:text-ink-DEFAULT"}`}
          onClick={() => dischargeValid && setStep("sdoh")}
          disabled={!dischargeValid}
        >
          <span className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold ${step === "sdoh" ? "bg-mint-deep text-white" : sdohReady ? "bg-triage-greenSoft text-triage-green" : "bg-muted text-ink-40"}`}>
            {sdohReady ? "✓" : "2"}
          </span>
          Social context
        </button>
      </div>

      {/* Step 1: Discharge */}
      {step === "discharge" && (
        <Card>
          <CardHeader>
            <CardTitle>Patient + discharge summary</CardTitle>
            <CardDescription>
              Required: name and phone. Paste the discharge note from your EMR.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <DischargeForm value={patient} onChange={setPatient} />
            <div className="flex justify-end">
              <Button
                onClick={() => setStep("sdoh")}
                disabled={!dischargeValid}
                title={!dischargeValid ? "Name and phone are required to continue" : ""}
              >
                Next
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Step 2: SDOH */}
      {step === "sdoh" && (
        <Card>
          <CardHeader>
            <CardTitle>Social determinants intake</CardTitle>
            <CardDescription>
              Plain-language answers classified into risk dimensions. Fill at least {SDOH_REQUIRED_COUNT} fields to enable onboarding.{" "}
              <span className={sdohReady ? "font-semibold text-triage-green" : "font-semibold text-triage-amber"}>
                {sdohFilled}/{8} filled
              </span>
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <SDOHForm value={sdoh} onChange={setSdoh} />

            {!sdohReady && (
              <div className="rounded-lg border border-triage-amber/30 bg-triage-amberSoft px-4 py-3 text-sm text-triage-amber">
                Fill at least {SDOH_REQUIRED_COUNT} social context fields to enable onboarding. ({sdohFilled} filled so far)
              </div>
            )}

            <div className="flex flex-wrap items-center justify-between gap-3">
              <button
                className="text-sm text-ink-40 hover:text-ink-DEFAULT"
                onClick={() => setStep("discharge")}
              >
                ← Back
              </button>
              <Button
                onClick={submit}
                disabled={submitting || !canSubmit}
                size="lg"
                title={!canSubmit ? "Complete required discharge fields and at least 3 SDOH fields first" : ""}
              >
                {submitting ? "Submitting…" : "Onboard patient"}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {duplicate && (
        <Card className="border-triage-amber/40 bg-triage-amberSoft">
          <CardContent className="flex flex-wrap items-center justify-between gap-3 p-4">
            <div className="flex items-start gap-3">
              <AlertCircle className="mt-0.5 h-5 w-5 text-triage-amber" />
              <div>
                <div className="font-semibold text-ink-DEFAULT">This patient already exists</div>
                <div className="text-sm text-ink-60">
                  A record for <strong>{duplicate.name}</strong> with phone <strong>{duplicate.phone}</strong> is
                  already in the system.
                </div>
              </div>
            </div>
            <Button asChild variant="primary">
              <Link to={`/patients/${duplicate.id}`}>Open existing patient</Link>
            </Button>
          </CardContent>
        </Card>
      )}

      {error && (
        <div className="card-base border-triage-red/30 bg-triage-redSoft p-4 text-sm text-triage-red">
          {error}
        </div>
      )}

      {success && (
        <Card className="border-mint bg-mint-soft">
          <CardContent className="flex items-center gap-3 p-4">
            <CheckCircle2 className="h-5 w-5 text-mint-deep" />
            <div className="text-sm">
              <div className="font-semibold text-ink-DEFAULT">Onboarded</div>
              <div className="text-ink-60">
                {typeof success.risk_score === "number" && (
                  <>Risk score <strong>{success.risk_score}</strong>. </>
                )}
                Opening patient view…
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
