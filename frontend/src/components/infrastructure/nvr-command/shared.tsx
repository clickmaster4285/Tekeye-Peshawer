import type { LucideIcon } from "lucide-react"
import type { ReactNode } from "react"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { cn } from "@/lib/utils"
import type { NvrHealthLevel } from "@/lib/infrastructure-api"

export function statusTone(status: string) {
  const s = (status || "").toLowerCase()
  if (
    s === "normal" ||
    s.includes("online") ||
    s === "ok" ||
    s === "up" ||
    s === "healthy" ||
    s === "connected" ||
    s === "active" ||
    s === "recording" ||
    s === "resolved" ||
    s === "good"
  ) {
    return "bg-emerald-50 text-emerald-800 border-emerald-200"
  }
  if (s === "sleep" || s === "sleeping" || s === "idle") {
    return "bg-slate-100 text-slate-800 border-slate-300"
  }
  if (s === "full" || s.includes("warning") || s.includes("degraded") || s.includes("attention")) {
    return "bg-amber-50 text-amber-900 border-amber-200"
  }
  if (
    s === "error" ||
    s === "abnormal" ||
    s === "offline" ||
    s === "unformatted" ||
    s.includes("fault") ||
    s.includes("critical") ||
    s === "down" ||
    s.includes("video loss")
  ) {
    return "bg-red-50 text-red-800 border-red-200"
  }
  if (s.includes("info") || s.includes("sync") || s.includes("process")) {
    return "bg-sky-50 text-sky-800 border-sky-200"
  }
  return "bg-slate-50 text-slate-700 border-slate-200"
}

export function healthDot(level: NvrHealthLevel | string | undefined) {
  const lv = (level || "unknown").toLowerCase()
  if (lv === "healthy" || lv === "normal" || lv === "good" || lv === "online" || lv === "ok") {
    return "bg-emerald-500"
  }
  if (lv === "sleep" || lv === "sleeping" || lv === "idle") return "bg-slate-400"
  if (lv === "warning" || lv === "full" || lv === "degraded") return "bg-amber-500"
  if (
    lv === "critical" ||
    lv === "error" ||
    lv === "abnormal" ||
    lv === "offline" ||
    lv === "unformatted"
  ) {
    return "bg-red-500"
  }
  return "bg-slate-400"
}

export function healthBadgeLabel(level: NvrHealthLevel | string | undefined, fallback = "Unknown") {
  const lv = (level || "").toLowerCase()
  if (lv === "healthy") return "Healthy"
  if (lv === "warning") return "Warning"
  if (lv === "critical") return "Critical"
  if (lv === "good") return "Good"
  return fallback
}

export function StatusBadge({
  status,
  className,
}: {
  status: string
  className?: string
}) {
  return (
    <Badge className={cn("border font-medium", statusTone(status), className)} variant="outline">
      <span className={cn("mr-1.5 inline-block h-1.5 w-1.5 rounded-full", healthDot(status))} />
      {status}
    </Badge>
  )
}

export function SectionCard({
  title,
  description,
  icon: Icon,
  actions,
  children,
  className,
  id,
}: {
  title: string
  description?: string
  icon?: LucideIcon
  actions?: ReactNode
  children: ReactNode
  className?: string
  id?: string
}) {
  return (
    <Card id={id} className={cn("scroll-mt-24 border-border/80 shadow-sm", className)}>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0 pb-3">
        <div className="min-w-0 space-y-1">
          <CardTitle className="flex items-center gap-2 text-base font-semibold tracking-tight">
            {Icon ? <Icon className="h-4 w-4 text-sky-600" /> : null}
            {title}
          </CardTitle>
          {description ? (
            <CardDescription className="text-xs leading-relaxed">{description}</CardDescription>
          ) : null}
        </div>
        {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}

export function MetricCard({
  label,
  value,
  status,
  icon: Icon,
  progress,
  onClick,
  accent = "sky",
}: {
  label: string
  value: ReactNode
  status?: string
  icon?: LucideIcon
  progress?: number | null
  onClick?: () => void
  accent?: "sky" | "emerald" | "amber" | "violet" | "slate"
}) {
  const accents = {
    sky: "bg-sky-50 text-sky-700",
    emerald: "bg-emerald-50 text-emerald-700",
    amber: "bg-amber-50 text-amber-700",
    violet: "bg-violet-50 text-violet-700",
    slate: "bg-slate-50 text-slate-700",
  }
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-xl border border-border/80 bg-white p-3.5 text-left shadow-sm transition",
        onClick && "hover:border-sky-300 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400",
      )}
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          {label}
        </span>
        {Icon ? (
          <span className={cn("flex h-7 w-7 items-center justify-center rounded-lg", accents[accent])}>
            <Icon className="h-3.5 w-3.5" />
          </span>
        ) : null}
      </div>
      <div className="text-xl font-semibold tabular-nums tracking-tight text-slate-900">{value}</div>
      {status ? (
        <div className="mt-1.5">
          <StatusBadge status={status} />
        </div>
      ) : null}
      {progress != null && !Number.isNaN(progress) ? (
        <Progress value={Math.min(100, Math.max(0, progress))} className="mt-2.5 h-1.5" />
      ) : null}
    </button>
  )
}

export function FieldRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="grid grid-cols-[9rem_1fr] items-start gap-3 border-b border-border/50 py-2.5 last:border-0 sm:grid-cols-[11rem_1fr]">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <span className="text-sm font-medium text-slate-900 break-all">{value ?? "—"}</span>
    </div>
  )
}

export function parseUsagePct(disks: { usage_pct?: number | null }[]): number | null {
  const vals = disks.map((d) => d.usage_pct).filter((v): v is number => v != null && !Number.isNaN(v))
  if (!vals.length) return null
  return Math.round((vals.reduce((a, b) => a + b, 0) / vals.length) * 10) / 10
}

export function managedHint() {
  return (
    <span className="inline-flex items-center rounded-full border border-sky-200 bg-sky-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-sky-700">
      Managed from TekeEye
    </span>
  )
}
