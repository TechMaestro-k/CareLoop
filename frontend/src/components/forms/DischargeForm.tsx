import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

export type PatientForm = {
  name: string;
  age: number | string;
  phone: string;
  email: string;
  language: string;
  channel_pref: string;
  caregiver_phone: string;
  caregiver_email: string;
  discharge_text: string;
  check_in_times_per_day: number;
};

export const DEFAULT_PATIENT_FORM: PatientForm = {
  name: "",
  age: "",
  phone: "",
  email: "",
  language: "en",
  channel_pref: "whatsapp_text",
  caregiver_phone: "",
  caregiver_email: "",
  discharge_text: "",
  check_in_times_per_day: 3,
};

export function DischargeForm({
  value,
  onChange,
}: {
  value: PatientForm;
  onChange: (v: PatientForm) => void;
}) {
  const set = <K extends keyof PatientForm>(k: K, v: PatientForm[K]) => onChange({ ...value, [k]: v });
  return (
    <div className="space-y-5">
      <div className="grid gap-4 md:grid-cols-2">
        <Field label="Patient name">
          <Input value={value.name} onChange={(e) => set("name", e.target.value)} placeholder="e.g. Asha Sharma" />
        </Field>
        <Field label="Age">
          <Input
            type="number"
            min={0}
            value={value.age}
            onChange={(e) => set("age", e.target.value === "" ? "" : Number(e.target.value))}
            placeholder="e.g. 68"
          />
        </Field>
        <Field label="Patient WhatsApp number" hint="Include country code, e.g. +1…">
          <Input value={value.phone} onChange={(e) => set("phone", e.target.value)} placeholder="+1…" />
        </Field>
        <Field label="Email">
          <Input type="email" value={value.email} onChange={(e) => set("email", e.target.value)} placeholder="patient@example.com" />
        </Field>
        <Field label="Preferred channel">
          <select
            className="flex h-10 w-full rounded-lg border border-input bg-surface px-3 text-sm focus-ring"
            value={value.channel_pref}
            onChange={(e) => set("channel_pref", e.target.value)}
          >
            <option value="whatsapp_text">WhatsApp · text</option>
            <option value="whatsapp_voice">WhatsApp · voice</option>
          </select>
        </Field>
        <Field label="Caregiver phone (optional)">
          <Input value={value.caregiver_phone} onChange={(e) => set("caregiver_phone", e.target.value)} placeholder="+1…" />
        </Field>
        <Field label="Caregiver email (optional)">
          <Input type="email" value={value.caregiver_email} onChange={(e) => set("caregiver_email", e.target.value)} placeholder="family@example.com" />
        </Field>
        <Field label="Check-ins per day" hint="How many times per day should CareLoop check on this patient? Default is 3 (morning, afternoon, evening).">
          <select
            className="flex h-10 w-full rounded-lg border border-input bg-surface px-3 text-sm focus-ring"
            value={value.check_in_times_per_day}
            onChange={(e) => set("check_in_times_per_day", Number(e.target.value))}
          >
            <option value={1}>1× per day</option>
            <option value={2}>2× per day</option>
            <option value={3}>3× per day (default)</option>
            <option value={4}>4× per day</option>
            <option value={6}>6× per day</option>
          </select>
        </Field>
      </div>
      <Field
        label="Discharge summary"
        hint="Free text. The Context Builder will extract diagnoses, medications, follow-ups."
      >
        <Textarea
          value={value.discharge_text}
          onChange={(e) => set("discharge_text", e.target.value)}
          rows={12}
          className="font-mono text-xs"
          placeholder="Patient: …, admitted for…, discharged on…, follow-up…"
        />
      </Field>
    </div>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {children}
      {hint && <p className="text-xs text-ink-40">{hint}</p>}
    </div>
  );
}
