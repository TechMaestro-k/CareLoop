import { lazy, Suspense, useMemo } from "react";

const ForceGraph2D = lazy(() => import("react-force-graph-2d"));

const KIND_COLORS: Record<string, string> = {
  diagnosis: "#0E7CB1",
  comorbidity: "#3FA0C7",
  medication: "#3FA875",
  sdoh: "#E8A33C",
  red_flag: "#E04050",
  route: "#7E5BD8",
  other: "#697383",
};

export function KGViewer({
  data,
  height = 480,
}: {
  data: { nodes: any[]; links: any[] } | null | undefined;
  height?: number;
}) {
  const safeData = useMemo(() => {
    if (!data || !Array.isArray(data.nodes)) return { nodes: [], links: [] };
    return data;
  }, [data]);

  if (!safeData.nodes.length) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-surface p-10 text-center text-sm text-ink-40">
        Knowledge graph will appear here once the patient is onboarded.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface">
      <Suspense fallback={<div className="p-10 text-center text-sm text-ink-40">Loading graph…</div>}>
        <ForceGraph2D
          graphData={safeData as any}
          height={height}
          width={undefined as any}
          nodeLabel={(n: any) => `${n.label} (${n.kind})`}
          nodeAutoColorBy={(n: any) => n.kind}
          nodeCanvasObject={(node: any, ctx: any, scale: number) => {
            const label = node.label || node.id;
            const color = KIND_COLORS[node.kind] || KIND_COLORS.other;
            ctx.fillStyle = color;
            ctx.beginPath();
            ctx.arc(node.x, node.y, 5, 0, 2 * Math.PI);
            ctx.fill();
            if (scale > 1.2) {
              ctx.font = `${10 / scale}px Inter, sans-serif`;
              ctx.fillStyle = "#0E1116";
              ctx.fillText(String(label).slice(0, 28), node.x + 6, node.y + 3);
            }
          }}
          linkColor={() => "#cbd5e1"}
          linkDirectionalArrowLength={3}
          linkDirectionalArrowRelPos={1}
          linkLabel={(l: any) => l.label || ""}
          cooldownTicks={80}
        />
      </Suspense>
      <div className="flex flex-wrap gap-3 border-t border-border bg-muted/40 p-3 text-xs">
        {Object.entries(KIND_COLORS).map(([k, c]) => (
          <div key={k} className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: c }} />
            <span className="text-ink-40">{k}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
