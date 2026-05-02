const BASE = (import.meta.env.VITE_API_BASE as string | undefined) || "";

export class ApiError extends Error {
  status: number;
  body: any;
  constructor(status: number, statusText: string, body: any) {
    const detailMsg =
      (body && typeof body === "object" && (body.detail?.message || body.detail)) ||
      (typeof body === "string" ? body : "") ||
      statusText;
    super(`${status} ${statusText} — ${typeof detailMsg === "string" ? detailMsg : JSON.stringify(detailMsg)}`);
    this.status = status;
    this.body = body;
  }
}

async function http<T = any>(path: string, init?: RequestInit): Promise<T> {
  const url = `${BASE}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    let body: any = text;
    try {
      body = JSON.parse(text);
    } catch {
      /* leave as text */
    }
    throw new ApiError(res.status, res.statusText, body);
  }
  if (res.status === 204) return null as unknown as T;
  return (await res.json()) as T;
}

export const api = {
  health: () => http("/api/healthz"),

  // patients
  listPatients: () => http<{ patients: any[] }>("/api/patients"),
  getPatient: (id: string) => http(`/api/patients/${id}`),
  onboard: (payload: any) =>
    http("/api/patients/onboard", { method: "POST", body: JSON.stringify(payload) }),
  deletePatient: (id: string) => http(`/api/patients/${id}`, { method: "DELETE" }),

  // doctor
  listEscalations: (status?: string) =>
    http<{ escalations: any[] }>(
      `/api/doctor/escalations${status ? `?status=${status}` : ""}`,
    ),
  getEscalation: (id: string) => http(`/api/doctor/escalations/${id}`),
  actionEscalation: (id: string, action: string, note?: string) =>
    http(`/api/doctor/escalations/${id}/action`, {
      method: "POST",
      body: JSON.stringify({ action, note }),
    }),

  // prompts
  listPrompts: () => http<{ prompts: any[] }>("/api/prompts"),
  getPrompt: (key: string) => http(`/api/prompts/${key}`),
  updatePrompt: (key: string, template: string) =>
    http(`/api/prompts/${key}`, {
      method: "PUT",
      body: JSON.stringify({ template, edited_by: "ui" }),
    }),
  insightsSummary: () =>
    http<{
      window_days: number;
      generated_at: string;
      totals: {
        patients: number;
        escalations_week: number;
        escalations_open: number;
      };
      severity_chart: { severity: string; count: number }[];
      sdoh_chart: { dimension: string; count: number }[];
    }>("/api/insights/summary"),

  reloadPrompts: () =>
    http<{ ok: boolean; cleared: { yaml_cleared: number; resolved_cleared: number }; prompts: any[] }>(
      "/api/prompts/_reload",
      { method: "POST" },
    ),

  // booking consult fee — gates doctor confirmation
  markBookingPaid: (proposalId: string) =>
    http(`/api/booking/${proposalId}/mark-paid`, { method: "POST" }),

  // booking — patient picker + doctor accept/reject
  getProposal: (id: string) =>
    http<{ proposal: any; patient: any; doctor_handoff_summary?: any }>(
      `/api/booking/${id}`,
    ),
  selectSlot: (id: string, slot_iso: string) =>
    http(`/api/booking/${id}/select`, {
      method: "POST",
      body: JSON.stringify({ slot_iso }),
    }),
  decideProposal: (id: string, action: "accept" | "reject" | "reschedule", note?: string) =>
    http(`/api/booking/${id}/decision`, {
      method: "POST",
      body: JSON.stringify({ action, note }),
    }),
  completeProposal: (id: string) =>
    http(`/api/booking/${id}/complete`, { method: "POST" }),
  listProposals: (params: { patient_status?: string; doctor_status?: string } = {}) => {
    const qs = new URLSearchParams(params as any).toString();
    return http<{ proposals: any[] }>(`/api/booking${qs ? `?${qs}` : ""}`);
  },
};
