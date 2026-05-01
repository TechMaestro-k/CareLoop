import { Badge } from "@/components/ui/badge";
import { severityClass } from "@/lib/utils";

const LABEL: Record<string, string> = {
  red: "Red · escalate",
  amber: "Amber · monitor",
  yellow: "Amber · monitor",
  green: "Green · routine",
};

export function TriageBadge({ severity, className }: { severity?: string; className?: string }) {
  const key = (severity || "green").toLowerCase();
  return (
    <Badge className={`${severityClass(key)} border-transparent ${className || ""}`.trim()}>
      {LABEL[key] || key}
    </Badge>
  );
}
