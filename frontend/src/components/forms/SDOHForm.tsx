import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

const FIELDS: { key: string; label: string; placeholder: string }[] = [
  { key: "lives_alone", label: "Living situation", placeholder: "e.g. lives alone, daughter in another city" },
  { key: "language", label: "Language & literacy", placeholder: "e.g. Hindi only, struggles with English" },
  { key: "transport", label: "Transport access", placeholder: "e.g. no own vehicle, depends on autorickshaw" },
  { key: "literacy", label: "Reading ability", placeholder: "e.g. can sign name, finds long instructions hard" },
  { key: "digital_comfort", label: "Phone & digital comfort", placeholder: "e.g. WhatsApp voice notes only" },
  { key: "income", label: "Financial situation", placeholder: "e.g. fixed pension, branded medicines feel expensive" },
  { key: "caregiver", label: "Caregiver / family support", placeholder: "e.g. daughter calls evenings, no one in same city" },
  { key: "housing", label: "Housing & mobility", placeholder: "e.g. ground floor home, lift available" },
];

export function SDOHForm({
  value,
  onChange,
}: {
  value: Record<string, string>;
  onChange: (v: Record<string, string>) => void;
}) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {FIELDS.map((f) => (
        <div key={f.key} className="space-y-1.5">
          <Label htmlFor={`sdoh-${f.key}`}>{f.label}</Label>
          <Textarea
            id={`sdoh-${f.key}`}
            placeholder={f.placeholder}
            value={value[f.key] || ""}
            onChange={(e) => onChange({ ...value, [f.key]: e.target.value })}
            rows={2}
          />
        </div>
      ))}
    </div>
  );
}
