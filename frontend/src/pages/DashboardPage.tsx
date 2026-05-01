import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  BarChart, Bar, CartesianGrid, XAxis, YAxis,
  Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import {
  ArrowRight, Users, AlertTriangle, ClipboardList,
  UserPlus, TrendingUp,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { TriageBadge } from "@/components/TriageBadge";
import { EmptyState } from "@/components/EmptyState";
import { api } from "@/lib/api";
import { formatTs, triageBarClass } from "@/lib/utils";

type Summary = Awaited<ReturnType<typeof api.insightsSummary>>;

const SEVERITY_FILL: Record<string, string> = {
  RED: "#E04050",
  AMBER: "#E8A33C",
  GREEN: "#3FA875",
};

const SDOH_LABEL: Record<string, string> = {
  financial_risk: "Financial risk",
  housing_risk: "Housing risk",
  transport_risk: "Transport gap",
  caregiver_risk: "Caregiver risk",
  digital_comfort_low: "Low digital comfort",
};

export default function DashboardPage() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [escalations, setEscalations] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [seeding, setSeeding] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [s, e] = await Promise.all([
        api.insightsSummary(),
        api.listEscalations("pending"),
      ]);
      setSummary(s);
      setEscalations(e.escalations || []);
    } catch (err: any) {
      setError(err.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, []);

  async function runSeed() {
    setSeeding(true);
    try {
      await api.seedDemo();
      await load();
    } catch (err: any) {
      setError(err.message || "Seed failed");
    } finally {
      setSeeding(false);
    }
  }

  const t = summary?.totals;

  const severityData = (summary?.severity_chart ?? []).filter((d) => d.count > 0);

  const sdohData = (summary?.sdoh_chart ?? [])
    .filter((d) => d.count > 0)
    .map((d) => ({ ...d, label: SDOH_LABEL[d.dimension] ?? d.dimension }));

  return (
    <div className="space-y-8 pb-6">

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="font-display text-2xl font-bold tracking-tight text-ink-DEFAULT">
            Population overview
          </h2>
          <p className="mt-0.5 text-sm text-ink-40">
            {summary
              ? `Last ${summary.window_days} days · updated ${formatTs(summary.generated_at)}`
              : "Loading…"}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="outline" size="sm">
            <Link to="/onboard" className="flex items-center gap-1.5">
              <UserPlus className="h-3.5 w-3.5" /> Onboard patient
            </Link>
          </Button>
          <Button onClick={runSeed} disabled={seeding} variant="ghost" size="sm">
            {seeding ? "Loading…" : "Load sample data"}
          </Button>
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-triage-red/30 bg-triage-redSoft px-4 py-3 text-sm text-triage-red">
          {error}
        </div>
      )}


      <section className="grid grid-cols-2 gap-3 lg:grid-cols-3">
        <KpiCard
          icon={<Users className="h-4 w-4" />}
          label="Active patients"
          value={t?.patients}
          loading={loading}
          accent="mint"
        />
        <KpiCard
          icon={<TrendingUp className="h-4 w-4" />}
          label="Escalations this week"
          value={t?.escalations_week}
          tone="amber"
          loading={loading}
          accent="amber"
        />
        <KpiCard
          icon={<AlertTriangle className="h-4 w-4" />}
          label="Open escalations"
          value={t?.escalations_open}
          tone={t && t.escalations_open > 0 ? "red" : "green"}
          loading={loading}
          accent={t && t.escalations_open > 0 ? "red" : "green"}
        />
      </section>


      <section className="grid gap-5 lg:grid-cols-2">

        <Card className="overflow-hidden">
          <CardHeader className="pb-0">
            <CardTitle className="text-base font-semibold">Escalations by severity</CardTitle>
            <CardDescription className="text-xs">
              Count of new escalations in the last 7 days
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-4">
            {severityData.length > 0 ? (
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={severityData} margin={{ left: -20, right: 8, top: 4, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#E5E9EF" vertical={false} />
                    <XAxis
                      dataKey="severity"
                      stroke="#B6BDC8"
                      tick={{ fill: "#697383", fontSize: 12 }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <YAxis
                      allowDecimals={false}
                      stroke="#B6BDC8"
                      tick={{ fill: "#697383", fontSize: 12 }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <Tooltip
                      cursor={{ fill: "rgba(168,230,201,0.12)" }}
                      contentStyle={{
                        borderRadius: 8,
                        border: "1px solid #E5E9EF",
                        fontSize: 12,
                        boxShadow: "0 2px 8px rgba(0,0,0,0.06)",
                      }}
                    />
                    <Bar dataKey="count" radius={[6, 6, 0, 0]} maxBarSize={56}>
                      {severityData.map((d) => (
                        <Cell key={d.severity} fill={SEVERITY_FILL[d.severity] ?? "#697383"} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <EmptyState
                title="No escalations this week"
                description="Escalations will appear here once patients interact with the agent."
              />
            )}
          </CardContent>
        </Card>


        <Card className="overflow-hidden">
          <CardHeader className="pb-0">
            <CardTitle className="text-base font-semibold">High-risk SDOH flags</CardTitle>
            <CardDescription className="text-xs">
              Patients currently flagged high-risk on each social determinant
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-4">
            {sdohData.length > 0 ? (
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={sdohData}
                    layout="vertical"
                    margin={{ left: 8, right: 24, top: 4, bottom: 0 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#E5E9EF" horizontal={false} />
                    <XAxis
                      type="number"
                      allowDecimals={false}
                      stroke="#B6BDC8"
                      tick={{ fill: "#697383", fontSize: 12 }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <YAxis
                      type="category"
                      dataKey="label"
                      stroke="#B6BDC8"
                      tick={{ fill: "#697383", fontSize: 11 }}
                      width={130}
                      axisLine={false}
                      tickLine={false}
                    />
                    <Tooltip
                      cursor={{ fill: "rgba(168,230,201,0.12)" }}
                      contentStyle={{
                        borderRadius: 8,
                        border: "1px solid #E5E9EF",
                        fontSize: 12,
                        boxShadow: "0 2px 8px rgba(0,0,0,0.06)",
                      }}
                    />
                    <Bar dataKey="count" fill="#5FCBA0" radius={[0, 6, 6, 0]} maxBarSize={28} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <EmptyState
                title="No SDOH flags yet"
                description="Patients with high-risk SDOH profiles will appear here."
              />
            )}
          </CardContent>
        </Card>
      </section>


      <section>
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h3 className="font-display text-base font-semibold text-ink-DEFAULT">
              Open escalations
            </h3>
            <p className="text-xs text-ink-40">Pending a clinician decision</p>
          </div>
          <Button asChild variant="ghost" size="sm" className="text-xs">
            <Link to="/doctor/inbox" className="flex items-center gap-1">
              Full inbox <ArrowRight className="h-3 w-3" />
            </Link>
          </Button>
        </div>

        {escalations.length === 0 ? (
          <Card>
            <CardContent className="py-8">
              <EmptyState
                icon={<ClipboardList className="h-5 w-5" />}
                title="All clear"
                description="No escalations are waiting for a decision right now."
              />
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-2">
            {escalations.slice(0, 6).map((e) => (
              <Link
                key={e.id}
                to={`/doctor/escalations/${e.id}`}
                className={`flex items-center gap-4 rounded-xl border border-transparent bg-white px-4 py-3 shadow-card transition hover:shadow-soft hover:border-border ${triageBarClass(e.severity)}`}
              >

                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-mint-soft text-xs font-bold text-mint-ink">
                  {(e.patient?.name || e.patient_id || "?")
                    .split(" ")
                    .slice(0, 2)
                    .map((w: string) => w[0])
                    .join("")
                    .toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-semibold text-ink-DEFAULT">
                      {e.patient?.name || e.patient_id || "Unknown patient"}
                    </span>
                    {e.patient?.age && (
                      <span className="text-xs text-ink-40">· {e.patient.age}y</span>
                    )}
                  </div>
                  <p className="truncate text-xs text-ink-60 mt-0.5">
                    {e.brief
                      ? e.brief.slice(0, 90) + (e.brief.length > 90 ? "…" : "")
                      : "Awaiting review"}
                  </p>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1.5">
                  <TriageBadge severity={e.severity} />
                  <span className="text-[11px] text-ink-40">{formatTs(e.created_at)}</span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

type AccentColor = "mint" | "amber" | "red" | "green";

function KpiCard({
  icon,
  label,
  value,
  tone,
  loading,
  accent,
}: {
  icon: React.ReactNode;
  label: string;
  value: number | string | undefined;
  tone?: "red" | "amber" | "green";
  loading: boolean;
  accent?: AccentColor;
}) {
  const valueClass =
    tone === "red"
      ? "text-triage-red"
      : tone === "amber"
        ? "text-triage-amber"
        : tone === "green"
          ? "text-triage-green"
          : "text-ink-DEFAULT";

  const iconBg: Record<AccentColor, string> = {
    mint: "bg-mint-soft text-mint-deep",
    amber: "bg-triage-amberSoft text-triage-amber",
    red: "bg-triage-redSoft text-triage-red",
    green: "bg-triage-greenSoft text-triage-green",
  };
  const iconStyle = iconBg[accent ?? "mint"];

  return (
    <Card className="overflow-hidden">
      <CardContent className="flex h-full flex-col justify-between p-5 min-h-[108px]">
        <div className="flex items-start justify-between gap-2">
          <p className="min-h-[2.5rem] text-xs font-medium uppercase tracking-wide text-ink-40 leading-snug">
            {label}
          </p>
          <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${iconStyle}`}>
            {icon}
          </span>
        </div>
        <div className={`mt-3 font-display text-3xl font-bold tabular-nums ${valueClass}`}>
          {loading && value === undefined ? (
            <span className="inline-block h-8 w-16 animate-pulse rounded-md bg-muted" />
          ) : (
            value ?? 0
          )}
        </div>
      </CardContent>
    </Card>
  );
}
