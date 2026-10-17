import type { Severity } from "@/lib/analytics-api"
import { cn } from "@/lib/utils"

/** Detection series — fixed order, validated categorical slots 1–4 (people, vehicles, weapons, plates). */
export const SERIES = [
  { key: "people", label: "People", color: "#2a78d6" },
  { key: "vehicles", label: "Vehicles", color: "#eb6834" },
  { key: "weapons", label: "Weapons", color: "#1baf7a" },
  { key: "plates", label: "Plates", color: "#eda100" },
] as const

/** Single-series charts use the first slot. */
export const SINGLE = SERIES[0].color

export const CHART_INK = {
  grid: "#e7e6e2",
  axis: "#8a8984",
  text: "#52514e",
}

/** Reserved status colors — always shown with the severity word, never alone. */
const SEVERITY_DOT: Record<Severity, string> = {
  Critical: "#d03b3b",
  High: "#ec835a",
  Medium: "#fab219",
  Low: "#a3a29c",
}

export function SeverityBadge({ severity, className }: { severity: Severity; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded border border-border bg-background px-1.5 py-0.5 text-[11px] font-medium text-foreground",
        className
      )}
    >
      <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: SEVERITY_DOT[severity] }} aria-hidden />
      {severity}
    </span>
  )
}

export function severityDot(severity: Severity): string {
  return SEVERITY_DOT[severity]
}
