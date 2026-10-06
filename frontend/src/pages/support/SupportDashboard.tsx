import { useQuery } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import {
  AlertTriangle,
  Boxes,
  CheckCircle2,
  Clock3,
  Code2,
  FileText,
  Hourglass,
  Inbox,
  Mail,
  MoreVertical,
  Plus,
  UserCheck,
  UserRound,
} from "lucide-react"
import { ModulePageLayout } from "@/components/dashboard/module-page-layout"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { ROUTES, getSupportTicketPath } from "@/routes/config"
import {
  PRIORITY_COLORS,
  STATUS_COLORS,
  fetchSupportDashboard,
  type SupportTicket,
  type SupportTrend,
} from "@/lib/support-api"
import { cn } from "@/lib/utils"

type Tone = {
  iconBg: string
  iconColor: string
  cardBg: string
  spark: string
}

const TONES: Record<string, Tone> = {
  blue: {
    iconBg: "bg-sky-100",
    iconColor: "text-sky-600",
    cardBg: "bg-gradient-to-br from-sky-50/80 to-white",
    spark: "#0ea5e9",
  },
  purple: {
    iconBg: "bg-violet-100",
    iconColor: "text-violet-600",
    cardBg: "bg-gradient-to-br from-violet-50/80 to-white",
    spark: "#8b5cf6",
  },
  red: {
    iconBg: "bg-red-100",
    iconColor: "text-red-600",
    cardBg: "bg-gradient-to-br from-red-50/70 to-white",
    spark: "#ef4444",
  },
  green: {
    iconBg: "bg-emerald-100",
    iconColor: "text-emerald-600",
    cardBg: "bg-gradient-to-br from-emerald-50/80 to-white",
    spark: "#10b981",
  },
  teal: {
    iconBg: "bg-teal-100",
    iconColor: "text-teal-600",
    cardBg: "bg-gradient-to-br from-teal-50/80 to-white",
    spark: "#14b8a6",
  },
  orange: {
    iconBg: "bg-orange-100",
    iconColor: "text-orange-600",
    cardBg: "bg-gradient-to-br from-orange-50/80 to-white",
    spark: "#f97316",
  },
  indigo: {
    iconBg: "bg-indigo-100",
    iconColor: "text-indigo-600",
    cardBg: "bg-gradient-to-br from-indigo-50/80 to-white",
    spark: "#6366f1",
  },
  sea: {
    iconBg: "bg-cyan-100",
    iconColor: "text-cyan-700",
    cardBg: "bg-gradient-to-br from-cyan-50/80 to-white",
    spark: "#0891b2",
  },
  pink: {
    iconBg: "bg-pink-100",
    iconColor: "text-pink-600",
    cardBg: "bg-gradient-to-br from-pink-50/80 to-white",
    spark: "#ec4899",
  },
  lightBlue: {
    iconBg: "bg-blue-100",
    iconColor: "text-blue-600",
    cardBg: "bg-gradient-to-br from-blue-50/80 to-white",
    spark: "#3b82f6",
  },
}

function Sparkline({ values, color }: { values: number[]; color: string }) {
  const w = 72
  const h = 28
  const pad = 2
  if (!values.length) {
    return <svg width={w} height={h} className="opacity-40" aria-hidden />
  }
  const max = Math.max(...values, 1)
  const min = Math.min(...values, 0)
  const span = Math.max(max - min, 1)
  const pts = values
    .map((v, i) => {
      const x = pad + (i / Math.max(values.length - 1, 1)) * (w - pad * 2)
      const y = h - pad - ((v - min) / span) * (h - pad * 2)
      return `${x},${y}`
    })
    .join(" ")
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="shrink-0" aria-hidden>
      <polyline
        fill="none"
        stroke={color}
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={pts}
      />
    </svg>
  )
}

function TrendLabel({ pct }: { pct: number }) {
  const flat = pct === 0
  const down = pct < 0
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 text-[11px] font-medium",
        flat && "text-muted-foreground",
        down && "text-emerald-600",
        !flat && !down && "text-red-500"
      )}
    >
      {flat ? "–" : down ? "↓" : "↑"} {Math.abs(pct)}%
      <span className="ml-0.5 font-normal text-muted-foreground">vs. last 7 days</span>
    </span>
  )
}

function KpiCard({
  label,
  value,
  href,
  icon: Icon,
  toneKey,
  trend,
}: {
  label: string
  value: number
  href: string
  icon: typeof Inbox
  toneKey: keyof typeof TONES
  trend?: SupportTrend
}) {
  const tone = TONES[toneKey]
  const spark = trend?.sparkline?.length ? trend.sparkline : [0, 0, 0, 0, 0, 0, 0]
  const pct = trend?.pct ?? 0

  return (
    <Link
      to={href}
      className={cn(
        "group flex flex-col rounded-xl border border-border/80 p-4 shadow-sm transition",
        "hover:border-sky-300 hover:shadow-md",
        tone.cardBg
      )}
    >
      <div className="flex items-start gap-3">
        <span
          className={cn(
            "flex h-9 w-9 shrink-0 items-center justify-center rounded-full",
            tone.iconBg
          )}
        >
          <Icon className={cn("h-4 w-4", tone.iconColor)} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-muted-foreground">{label}</p>
          <p className="mt-0.5 text-2xl font-semibold tabular-nums tracking-tight text-foreground">
            {value}
          </p>
        </div>
      </div>
      <div className="mt-3 flex items-end justify-between gap-2">
        <TrendLabel pct={pct} />
        <Sparkline values={spark} color={tone.spark} />
      </div>
    </Link>
  )
}

function priorityDisplay(priority: string) {
  if (priority === "P1") return { label: "High", className: PRIORITY_COLORS.P1 }
  if (priority === "P2") return { label: "Medium", className: PRIORITY_COLORS.P2 }
  if (priority === "P3") return { label: "Low", className: "bg-emerald-100 text-emerald-800" }
  return { label: "Low", className: PRIORITY_COLORS.P4 || "bg-slate-100 text-slate-700" }
}

function formatCreated(iso: string) {
  try {
    const d = new Date(iso)
    const date = d.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    })
    const time = d.toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
    })
    return { date, time }
  } catch {
    return { date: iso, time: "" }
  }
}

function RecentTable({ tickets }: { tickets: SupportTicket[] }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border/80 bg-white shadow-sm">
      <div className="flex items-center justify-between gap-3 border-b px-5 py-4">
        <h2 className="text-base font-semibold text-foreground">Recent Support Requests</h2>
        <Button asChild variant="link" className="h-auto p-0 text-sky-600">
          <Link to={ROUTES.SUPPORT_ALL}>
            View All <span className="ml-0.5">›</span>
          </Link>
        </Button>
      </div>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="pl-5">ID</TableHead>
              <TableHead>Title</TableHead>
              <TableHead>Priority</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Created On</TableHead>
              <TableHead className="pr-5 text-right">Action</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {tickets.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="py-12 text-center text-muted-foreground">
                  No recent support requests.
                </TableCell>
              </TableRow>
            )}
            {tickets.map((t) => {
              const pri = priorityDisplay(t.priority)
              const created = formatCreated(t.created_at)
              const sub = [t.department_label, t.category_label || t.asset_label]
                .filter(Boolean)
                .join(" • ")
              return (
                <TableRow key={t.id} className="hover:bg-slate-50/60">
                  <TableCell className="pl-5 font-medium text-sky-700 whitespace-nowrap">
                    {t.ticket_number.startsWith("#") ? t.ticket_number : `#${t.ticket_number}`}
                  </TableCell>
                  <TableCell className="max-w-[280px]">
                    <div className="truncate font-medium text-foreground">{t.title}</div>
                    {sub ? (
                      <div className="truncate text-xs text-muted-foreground">{sub}</div>
                    ) : null}
                  </TableCell>
                  <TableCell>
                    <Badge className={cn("font-normal", pri.className)} variant="secondary">
                      {pri.label}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge
                      className={cn("font-normal", STATUS_COLORS[t.status] || "")}
                      variant="secondary"
                    >
                      {t.status_label}
                    </Badge>
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-sm">
                    <div className="text-foreground">{created.date}</div>
                    <div className="text-xs text-muted-foreground">{created.time}</div>
                  </TableCell>
                  <TableCell className="pr-5">
                    <div className="flex items-center justify-end gap-1">
                      <Button asChild size="sm" variant="outline" className="h-8 px-3">
                        <Link to={getSupportTicketPath(t.id)}>View</Link>
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-8 w-8 text-muted-foreground"
                        asChild
                      >
                        <Link to={getSupportTicketPath(t.id)} aria-label="More">
                          <MoreVertical className="h-4 w-4" />
                        </Link>
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

export default function SupportDashboard() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["support", "dashboard"],
    queryFn: fetchSupportDashboard,
    refetchInterval: 15000,
  })

  const caps = data?.capabilities
  const c = (data?.counts || {}) as Record<string, number>
  const trends = data?.trends || {}
  const recent = data?.recent || []
  const requesterOnly = Boolean(caps?.is_requester_only)

  const num = (key: string) => Number(c[key] || 0)

  return (
    <ModulePageLayout
      title={requesterOnly ? "My Requests" : "Support Dashboard"}
      description={
        requesterOnly
          ? "Create a request for Support. Support reviews, assigns, and closes the ticket."
          : "Support receives requests, triages, assigns to IT/Developer, verifies, and closes."
      }
      breadcrumbs={[
        { label: "Requests & Support", href: ROUTES.SUPPORT_CREATE },
        { label: requesterOnly ? "Overview" : "Dashboard" },
      ]}
      actions={
        <Button asChild className="bg-sky-600 hover:bg-sky-700">
          <Link to={ROUTES.SUPPORT_CREATE}>
            <Plus className="mr-2 h-4 w-4" />
            New Request
          </Link>
        </Button>
      }
    >
      {isLoading && <p className="text-sm text-muted-foreground">Loading dashboard…</p>}
      {error && (
        <p className="text-sm text-red-600">
          {(error as Error).message || "Failed to load dashboard"}
        </p>
      )}

      {data && requesterOnly && (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <KpiCard
              label="My open requests"
              value={num("my_requests") || num("total_open")}
              href={`${ROUTES.SUPPORT_ALL}?queue=my_requests`}
              icon={Inbox}
              toneKey="blue"
              trend={trends.my_requests}
            />
            <KpiCard
              label="Waiting my confirmation"
              value={num("waiting_client")}
              href={`${ROUTES.SUPPORT_ALL}?queue=waiting_client`}
              icon={Hourglass}
              toneKey="green"
              trend={trends.waiting_client}
            />
            <KpiCard
              label="Closed"
              value={num("closed")}
              href={`${ROUTES.SUPPORT_ALL}?queue=closed`}
              icon={CheckCircle2}
              toneKey="teal"
              trend={trends.closed}
            />
          </div>
          <RecentTable tickets={recent} />
        </div>
      )}

      {data && !requesterOnly && (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <KpiCard
              label="Open"
              value={num("total_open")}
              href={ROUTES.SUPPORT_ALL}
              icon={FileText}
              toneKey="blue"
              trend={trends.total_open}
            />
            <KpiCard
              label="New / Review"
              value={num("new")}
              href={`${ROUTES.SUPPORT_ALL}?queue=review`}
              icon={Clock3}
              toneKey="purple"
              trend={trends.new}
            />
            <KpiCard
              label="SLA Breached"
              value={num("sla_breached")}
              href={`${ROUTES.SUPPORT_ALL}?queue=sla`}
              icon={AlertTriangle}
              toneKey="red"
              trend={trends.sla_breached}
            />
            <KpiCard
              label="Waiting Client"
              value={num("waiting_client")}
              href={`${ROUTES.SUPPORT_ALL}?queue=waiting_client`}
              icon={Hourglass}
              toneKey="green"
              trend={trends.waiting_client}
            />
            <KpiCard
              label="Unassigned"
              value={num("unassigned")}
              href={`${ROUTES.SUPPORT_ALL}?queue=unassigned`}
              icon={UserRound}
              toneKey="teal"
              trend={trends.unassigned}
            />
            <KpiCard
              label="Resolution Submitted"
              value={num("resolution_submitted")}
              href={`${ROUTES.SUPPORT_ALL}?queue=resolution_submitted`}
              icon={CheckCircle2}
              toneKey="orange"
              trend={trends.resolution_submitted}
            />
            <KpiCard
              label="IT Queue"
              value={num("it_queue")}
              href={`${ROUTES.SUPPORT_ALL}?queue=it`}
              icon={Code2}
              toneKey="indigo"
              trend={trends.it_queue}
            />
            <KpiCard
              label="Developer Queue"
              value={num("developer_queue")}
              href={`${ROUTES.SUPPORT_ALL}?queue=developer`}
              icon={Boxes}
              toneKey="sea"
              trend={trends.developer_queue}
            />
            <KpiCard
              label="Assigned to Me"
              value={num("my_assigned")}
              href={`${ROUTES.SUPPORT_ALL}?queue=assigned_to_me`}
              icon={UserCheck}
              toneKey="pink"
              trend={trends.my_assigned}
            />
            <KpiCard
              label="My Requests"
              value={num("my_requests")}
              href={`${ROUTES.SUPPORT_ALL}?queue=my_requests`}
              icon={Mail}
              toneKey="lightBlue"
              trend={trends.my_requests}
            />
          </div>

          <RecentTable tickets={recent} />
        </div>
      )}
    </ModulePageLayout>
  )
}
