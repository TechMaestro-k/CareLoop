import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function severityClass(s?: string) {
  const v = (s || "").toLowerCase();
  if (v === "red") return "severity-red";
  if (v === "amber" || v === "yellow") return "severity-amber";
  return "severity-green";
}

export function triageBarClass(s?: string) {
  const v = (s || "").toLowerCase();
  if (v === "red") return "triage-bar-red";
  if (v === "amber" || v === "yellow") return "triage-bar-amber";
  return "triage-bar-green";
}

export function formatTs(ts?: string) {
  if (!ts) return "";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

export function formatDateShort(ts?: string) {
  if (!ts) return "";
  try {
    return new Date(ts).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    });
  } catch {
    return ts;
  }
}

export function formatTimeShort(ts?: string) {
  if (!ts) return "";
  try {
    return new Date(ts).toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return ts;
  }
}

export function initials(name?: string) {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/).slice(0, 2);
  return parts.map((p) => p[0]).join("").toUpperCase();
}
