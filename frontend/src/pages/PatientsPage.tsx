import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronRight, UserPlus, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { TriageBadge } from "@/components/TriageBadge";
import { EmptyState } from "@/components/EmptyState";
import { api } from "@/lib/api";
import { initials, triageBarClass } from "@/lib/utils";

const SDOH_CHIPS: Array<{ key: string; match: any; label: string }> = [
  { key: "financial_risk", match: "high", label: "Financial risk" },
  { key: "caregiver_risk", match: "high", label: "Lives alone" },
  { key: "transport_risk", match: "high", label: "Transport gap" },
  { key: "digital_comfort", match: "low", label: "Low digital comfort" },
  { key: "literacy_level", match: "low", label: "Low literacy" },
];

export default function PatientsPage() {
  const [patients, setPatients] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");

  useEffect(() => {
    api
      .listPatients()
      .then((d) => setPatients(d.patients || []))
      .catch(() => setPatients([]))
      .finally(() => setLoading(false));
  }, []);

  const filtered = query
    ? patients.filter((p) => (p.name || "").toLowerCase().includes(query.toLowerCase()))
    : patients;

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="font-display text-2xl font-bold tracking-tight">Patients</h2>
          <p className="text-sm text-ink-40">Everyone currently being followed.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by name…"
            className="h-10 w-56 rounded-lg border border-input bg-surface px-3 text-sm focus-ring"
          />
          <Button asChild>
            <Link to="/onboard" className="flex items-center gap-1">
              <UserPlus className="h-4 w-4" /> Onboard
            </Link>
          </Button>
        </div>
      </header>

      {loading ? (
        <div className="grid gap-3 md:grid-cols-2">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-24 animate-pulse rounded-xl bg-muted" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<Users className="h-5 w-5" />}
          title={query ? "No matches" : "No patients yet"}
          description={query ? "Try a different name." : "Onboard the first patient to get started."}
          action={
            !query && (
              <Button asChild>
                <Link to="/onboard">Onboard a patient</Link>
              </Button>
            )
          }
        />
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {filtered.map((p) => (
            <PatientCard key={p.id} patient={p} />
          ))}
        </div>
      )}
    </div>
  );
}

function PatientCard({ patient }: { patient: any }) {
  const sev = patient.latest_severity || patient.severity || "green";
  const sdohChips = SDOH_CHIPS.filter(
    (c) => patient.sdoh && patient.sdoh[c.key] === c.match,
  );
  const visibleChips = sdohChips.slice(0, 2);
  const extraChips = sdohChips.length - visibleChips.length;

  return (
    <Link to={`/patients/${patient.id}`} className="group block h-full">
      <Card className={`h-full transition hover:shadow-soft ${triageBarClass(sev)}`}>
        <CardContent className="flex min-h-[96px] items-start gap-4 p-4">
          <div className="mt-0.5 flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-mint-soft font-display text-base font-semibold text-mint-ink">
            {initials(patient.name)}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <div className="truncate font-display text-base font-semibold text-ink-DEFAULT">
                {patient.name}
              </div>
              <span className="text-xs text-ink-40">· {patient.age || "?"}y</span>
              <TriageBadge severity={sev} className="ml-auto" />
            </div>
            <div className="mt-0.5 flex items-center gap-3 truncate text-sm text-ink-60">
              <span className="truncate">{patient.diagnosis || "Awaiting clinical extraction…"}</span>
              {patient.risk_score != null && (
                <span
                  className={`shrink-0 text-xs font-semibold ${
                    patient.risk_score >= 0.7
                      ? "text-triage-red"
                      : patient.risk_score >= 0.45
                        ? "text-triage-amber"
                        : "text-triage-green"
                  }`}
                >
                  Risk {(patient.risk_score * 100).toFixed(0)}%
                </span>
              )}
            </div>
            <div className="mt-2 flex min-h-[1.5rem] flex-wrap items-center gap-1.5">
              {visibleChips.map((c) => (
                <span key={c.key} className="chip">{c.label}</span>
              ))}
              {extraChips > 0 && (
                <span className="chip text-ink-40">+{extraChips}</span>
              )}
            </div>
          </div>
          <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-ink-40 transition group-hover:text-ink-DEFAULT" />
        </CardContent>
      </Card>
    </Link>
  );
}
