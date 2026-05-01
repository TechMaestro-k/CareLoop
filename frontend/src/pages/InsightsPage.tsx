import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Cell,
} from "recharts";
import { RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const SDOH_LABEL: Record<string, string> = {
  financial_risk: "Financial",
  housing_risk: "Housing",
  transport_risk: "Transport",
  caregiver_risk: "Caregiver",
  digital_comfort_low: "Low digital",
};

const SEVERITY_FILL: Record<string, string> = {
  RED: "#E04050",
  AMBER: "#E8A33C",
  GREEN: "#3FA875",
};

function StatCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: number | string;
  hint?: string;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{label}</CardDescription>
        <CardTitle className="font-display text-3xl tabular-nums text-ink-DEFAULT">
          {value}
        </CardTitle>
      </CardHeader>
      {hint ? (
        <CardContent className="pt-0 text-xs text-ink-40">{hint}</CardContent>
      ) : null}
    </Card>
  );
}

export default function InsightsPage() {
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setData(await api.insightsSummary());
    } catch (e: any) {
      setError(e?.message || "Failed to load insights");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const totals = data?.totals;
  const sdohChart = (data?.sdoh_chart || []).map((row: any) => ({
    ...row,
    label: SDOH_LABEL[row.dimension] || row.dimension,
  }));

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-display text-2xl font-bold tracking-tight">Insights</h2>
          <p className="text-sm text-ink-60">
            7-day rollup of escalations and SDOH risk across the cohort.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className="h-3.5 w-3.5" />
          {loading ? "Refreshing…" : "Refresh"}
        </Button>
      </div>

      {error && (
        <div className="card-base border-triage-red/30 bg-triage-redSoft p-4 text-sm text-triage-red">
          {error}
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <StatCard label="Patients enrolled" value={totals?.patients ?? "—"} />
        <StatCard
          label="Escalations (7d)"
          value={totals?.escalations_week ?? "—"}
          hint={`${totals?.escalations_open ?? 0} still open`}
        />
        <StatCard
          label="High-risk SDOH flags"
          value={(data?.sdoh_chart || []).reduce((acc: number, r: any) => acc + r.count, 0)}
          hint="Across all dimensions"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Escalations by severity (7d)</CardTitle>
            <CardDescription>
              RED = doctor needed now, AMBER = within 24h, GREEN = info only.
            </CardDescription>
          </CardHeader>
          <CardContent className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data?.severity_chart || []}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E2E8EF" />
                <XAxis dataKey="severity" stroke="#697383" />
                <YAxis allowDecimals={false} stroke="#697383" />
                <Tooltip />
                <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                  {(data?.severity_chart || []).map((r: any, i: number) => (
                    <Cell key={i} fill={SEVERITY_FILL[r.severity] || "#5FCBA0"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">High-risk SDOH dimensions</CardTitle>
            <CardDescription>Patients flagged as high-risk on each axis.</CardDescription>
          </CardHeader>
          <CardContent className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={sdohChart}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E2E8EF" />
                <XAxis dataKey="label" stroke="#697383" />
                <YAxis allowDecimals={false} stroke="#697383" />
                <Tooltip />
                <Bar dataKey="count" fill="#5FCBA0" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      {data && (
        <p className="text-xs text-ink-40">
          Generated {new Date(data.generated_at).toLocaleString()} · window {data.window_days}{" "}
          days
        </p>
      )}
    </div>
  );
}
