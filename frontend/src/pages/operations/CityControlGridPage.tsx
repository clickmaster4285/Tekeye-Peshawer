import { useEffect, useMemo, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import {
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  Bell,
  BrainCircuit,
  Camera,
  ChevronDown,
  Headset,
  LayoutGrid,
  MapPin,
  Search,
  Server,
  Shield,
  SignalHigh,
  SignalLow,
  SignalZero,
  UserRound,
  Zap,
} from "lucide-react"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { CityStatusMap } from "@/components/city-control/CityStatusMap"
import { DetectionThumb } from "@/components/city-control/detection-thumb"
import {
  CITY_CONTROL_REFRESH_MS,
  fetchCityControlGridLive,
  zeroCityControlKpis,
  type CityControlAlert,
  type CityControlKpi,
  type CityControlRow,
  type CityStatus,
  type Connectivity,
} from "@/data/city-control-grid-data"
import { ROUTES } from "@/routes/config"
import { cn } from "@/lib/utils"

const STATUS_COLOR: Record<CityStatus, string> = {
  Online: "#12A66A",
  Offline: "#FF4D59",
  Degraded: "#FF9D2E",
}

const KPI_TONE = {
  blue: { border: "border-[#BFDBFE]", iconBg: "bg-[#EFF6FF]", icon: "text-[#2563EB]", Icon: Camera },
  purple: { border: "border-[#DDD6FE]", iconBg: "bg-[#F5F3FF]", icon: "text-[#7C3AED]", Icon: BrainCircuit },
  red: { border: "border-[#FECACA]", iconBg: "bg-[#FEF2F2]", icon: "text-[#EF4444]", Icon: Shield },
  orange: { border: "border-[#FED7AA]", iconBg: "bg-[#FFF7ED]", icon: "text-[#F59E0B]", Icon: UserRound },
  green: { border: "border-[#A7F3D0]", iconBg: "bg-[#ECFDF5]", icon: "text-[#10B981]", Icon: Server },
} as const

function ConnectivityIcon({ value }: { value: Connectivity }) {
  if (value === "Good") return <SignalHigh className="h-3.5 w-3.5 text-[#12A66A]" />
  if (value === "Limited") return <SignalLow className="h-3.5 w-3.5 text-[#FF9D2E]" />
  return <SignalZero className="h-3.5 w-3.5 text-[#FF4D59]" />
}

function MetricCell({
  label,
  fill,
  color,
  sub,
}: {
  label: string
  fill: number
  color: string
  sub?: string
}) {
  return (
    <div className="min-w-[76px]">
      <p className="text-[12px] font-semibold tabular-nums text-[#102C55]">
        {label}
        {sub ? <span className="font-medium text-[#607DA5]"> / {sub}</span> : null}
      </p>
      <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-[#E8F0FA]">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${Math.max(0, Math.min(100, fill))}%`, backgroundColor: color }}
        />
      </div>
    </div>
  )
}

type StatusFilter = "all" | CityStatus

export default function CityControlGridPage() {
  const navigate = useNavigate()
  const [query, setQuery] = useState("")
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all")
  const [rows, setRows] = useState<CityControlRow[]>([])
  const [kpis, setKpis] = useState<CityControlKpi[]>(() => zeroCityControlKpis())
  const [alerts, setAlerts] = useState<CityControlAlert[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const ac = new AbortController()
    setLoading(true)
    const load = (force: boolean) =>
      fetchCityControlGridLive({ signal: ac.signal, force })
        .then((live) => {
          if (ac.signal.aborted) return
          setRows(live.rows)
          setKpis(live.kpis)
          setAlerts(live.alerts)
        })
        .catch(() => {
          // Keep the last good data on a failed refresh.
        })
        .finally(() => {
          if (!ac.signal.aborted) setLoading(false)
        })
    void load(false)
    const timer = window.setInterval(() => void load(true), CITY_CONTROL_REFRESH_MS)
    return () => {
      window.clearInterval(timer)
      ac.abort()
    }
  }, [])

  const cities = useMemo(() => {
    const q = query.trim().toLowerCase()
    return rows.filter((c) => {
      if (statusFilter !== "all" && c.status !== statusFilter) return false
      if (!q) return true
      return c.city.toLowerCase().includes(q)
    })
  }, [query, rows, statusFilter])

  const openCity = (city: CityControlRow) => {
    navigate(`${ROUTES.CITY_CONTROL_GRID}/${city.id}`)
  }

  return (
    <div className="flex w-full min-w-0 max-w-full flex-col gap-4">
      {/* Header */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="flex min-w-0 items-start gap-2.5">
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#F5F3FF]">
            <LayoutGrid className="h-[18px] w-[18px] text-[#7C3AED]" />
          </div>
          <div className="min-w-0">
            <h1 className="text-[22px] font-bold tracking-tight text-[#102C55]">City Control Grid</h1>
            <p className="mt-0.5 text-[13px] text-[#607DA5]">
              Monitor all cities at a glance. Click a city for detailed read-only analytics.
            </p>
          </div>
        </div>

        <div className="flex w-full flex-col gap-2 sm:flex-row sm:items-center lg:w-auto">
          <label className="relative block w-full sm:w-[220px]">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#607DA5]" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search city..."
              className="h-9 w-full rounded-lg border border-[#D9E6F5] bg-white pl-8 pr-3 text-[13px] text-[#102C55] outline-none placeholder:text-[#90A7C4] focus:border-[#0875E1] focus:ring-2 focus:ring-[#0875E1]/20"
            />
          </label>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
            className="h-9 w-full rounded-lg border border-[#D9E6F5] bg-white px-3 text-[13px] font-medium text-[#102C55] outline-none focus:border-[#0875E1] focus:ring-2 focus:ring-[#0875E1]/20 sm:w-[140px]"
            aria-label="Filter cities"
          >
            <option value="all">All Cities</option>
            <option value="Online">Online</option>
            <option value="Degraded">Degraded</option>
            <option value="Offline">Offline</option>
          </select>
        </div>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-5">
        {kpis.map((kpi) => {
          const tone = KPI_TONE[kpi.tone]
          const Icon = tone.Icon
          return (
            <div
              key={kpi.id}
              className={cn(
                "rounded-[10px] border bg-white px-3.5 py-3 shadow-[0_1px_2px_rgba(16,44,85,0.04)]",
                tone.border
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <p className="text-[12px] font-medium text-[#607DA5]">{kpi.label}</p>
                <div className={cn("flex h-8 w-8 items-center justify-center rounded-lg", tone.iconBg)}>
                  <Icon className={cn("h-[18px] w-[18px]", tone.icon)} />
                </div>
              </div>
              <div className="mt-1.5 flex items-end gap-2">
                <p className="text-[26px] font-bold leading-none tracking-tight text-[#102C55]">{kpi.value}</p>
                {kpi.delta ? (
                  <span className="mb-0.5 inline-flex items-center gap-0.5 text-[11px] font-semibold text-[#12A66A]">
                    <ArrowUpRight className="h-3 w-3" />
                    {kpi.delta}
                  </span>
                ) : null}
              </div>
              <p className="mt-2 text-[11px] leading-snug text-[#607DA5]">{kpi.support}</p>
            </div>
          )
        })}
      </div>

      {/* Cities Overview table */}
      <div className="overflow-hidden rounded-[10px] border border-[#D9E6F5] bg-white shadow-[0_1px_2px_rgba(16,44,85,0.04)]">
        <div className="border-b border-[#D9E6F5] px-4 py-3">
          <h2 className="text-[15px] font-semibold text-[#102C55]">Cities Overview</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-0 border-collapse text-left">
            <thead>
              <tr className="bg-[#F2F7FC] text-[11px] font-semibold uppercase tracking-wide text-[#607DA5]">
                <th className="px-3 py-2.5">#</th>
                <th className="px-3 py-2.5">City</th>
                <th className="px-3 py-2.5">Status</th>
                <th className="px-3 py-2.5">Cameras</th>
                <th className="px-3 py-2.5">AI Detections (24h)</th>
                <th className="px-3 py-2.5">Seizures (30d)</th>
                <th className="px-3 py-2.5">Detentions (30d)</th>
                <th className="px-3 py-2.5">Last Sync</th>
                <th className="px-3 py-2.5">Connectivity</th>
                <th className="px-3 py-2.5">Actions</th>
              </tr>
            </thead>
            <tbody>
              {cities.map((row) => {
                const camColor =
                  row.status === "Offline"
                    ? STATUS_COLOR.Offline
                    : row.status === "Degraded"
                      ? STATUS_COLOR.Degraded
                      : STATUS_COLOR.Online
                return (
                  <tr
                    key={row.id}
                    className="cursor-pointer border-t border-[#E8F0FA] transition hover:bg-[#F7FAFD]"
                    onClick={() => openCity(row)}
                  >
                    <td className="px-3 py-2.5 text-[12px] tabular-nums text-[#607DA5]">{row.rank}</td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-1.5">
                        <MapPin className="h-3.5 w-3.5 text-[#0875E1]" />
                        <span className="text-[13px] font-semibold text-[#102C55]">{row.city}</span>
                        {row.isHq ? (
                          <span className="rounded bg-[#0875E1] px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-white">
                            HQ
                          </span>
                        ) : null}
                      </div>
                    </td>
                    <td className="px-3 py-2.5">
                      <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-[#102C55]">
                        <span
                          className="h-2 w-2 rounded-full"
                          style={{ backgroundColor: STATUS_COLOR[row.status] }}
                        />
                        {row.status}
                      </span>
                    </td>
                    <td className="px-3 py-2.5">
                      <MetricCell
                        label={String(row.camerasOnline)}
                        sub={String(row.camerasTotal)}
                        fill={row.bars.cameras}
                        color={camColor}
                      />
                    </td>
                    <td className="px-3 py-2.5">
                      <MetricCell
                        label={row.aiDetections24h.toLocaleString()}
                        fill={row.bars.ai}
                        color="#7552E8"
                      />
                    </td>
                    <td className="px-3 py-2.5">
                      <MetricCell label={String(row.seizures30d)} fill={row.bars.seizures} color="#FF4D59" />
                    </td>
                    <td className="px-3 py-2.5">
                      <MetricCell
                        label={String(row.detentions30d)}
                        fill={row.bars.detentions}
                        color="#FF9D2E"
                      />
                    </td>
                    <td className="px-3 py-2.5">
                      <p className="text-[12px] text-[#607DA5]">{row.lastSync}</p>
                      <p
                        className={cn(
                          "text-[10px] font-medium",
                          row.status === "Offline" ? "text-[#FF4D59]" : "text-[#90A7C4]"
                        )}
                      >
                        {row.status === "Offline" ? `Last known · ${row.lastSyncRelative}` : row.lastSyncRelative}
                      </p>
                    </td>
                    <td className="px-3 py-2.5">
                      <span
                        className={cn(
                          "inline-flex items-center gap-1 text-[12px] font-medium",
                          row.connectivity === "Good" && "text-[#12A66A]",
                          row.connectivity === "Limited" && "text-[#FF9D2E]",
                          row.connectivity === "No Signal" && "text-[#FF4D59]"
                        )}
                      >
                        <ConnectivityIcon value={row.connectivity} />
                        {row.connectivity}
                      </span>
                    </td>
                    <td className="px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center gap-1.5">
                        <button
                          type="button"
                          onClick={() => openCity(row)}
                          className="h-7 rounded-md bg-[#0875E1] px-3 text-[12px] font-semibold text-white transition hover:bg-[#086BC6]"
                        >
                          View
                        </button>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <button
                              type="button"
                              className="flex h-7 w-7 items-center justify-center rounded-md border border-[#D9E6F5] bg-white text-[#607DA5] hover:bg-[#F4F8FD]"
                              aria-label={`Actions for ${row.city}`}
                            >
                              <ChevronDown className="h-3.5 w-3.5" />
                            </button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" className="w-44">
                            <DropdownMenuItem onClick={() => openCity(row)}>City summary</DropdownMenuItem>
                            <DropdownMenuItem
                              disabled={row.status === "Offline"}
                              onClick={() => navigate(ROUTES.ALL_CITIES_CAMERAS)}
                            >
                              Open cameras
                            </DropdownMenuItem>
                            <DropdownMenuItem>Export snapshot</DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    </td>
                  </tr>
                )
              })}
              {cities.length === 0 ? (
                <tr>
                  <td colSpan={10} className="px-4 py-10 text-center text-sm text-[#607DA5]">
                    {loading ? "Loading live city data…" : "No cities match your filters."}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>

      {/* Bottom panels */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <CityStatusMap tall className="min-h-[420px] xl:min-h-full" rows={rows} />

        {/* Alerts */}
        <div className="flex min-h-[300px] flex-col overflow-hidden rounded-[10px] border border-[#D9E6F5] bg-white shadow-[0_1px_2px_rgba(16,44,85,0.04)]">
          <div className="flex items-center justify-between border-b border-[#D9E6F5] px-4 py-3">
            <h2 className="inline-flex items-center gap-1.5 text-[15px] font-semibold text-[#102C55]">
              <Bell className="h-4 w-4 text-[#607DA5]" />
              Recent Alerts
            </h2>
            <Link to={ROUTES.AI_MONITORING} className="text-[12px] font-semibold text-[#0875E1] hover:underline">
              View All
            </Link>
          </div>
          <ul className="max-h-[420px] flex-1 divide-y divide-[#E8F0FA] overflow-y-auto">
            {alerts.length === 0 ? (
              <li className="px-4 py-8 text-center text-[13px] text-[#607DA5]">
                {loading ? "Loading alerts…" : "No recent alerts."}
              </li>
            ) : (
              alerts.map((alert) => {
                const badge =
                  alert.severity === "Info"
                    ? "border-[#BFE8D4] bg-[#E8F8F1] text-[#12A66A]"
                    : alert.severity === "Medium"
                      ? "border-[#FFE0B8] bg-[#FFF4E8] text-[#D97706]"
                      : "border-[#F7C9CD] bg-[#FFECEE] text-[#FF4D59]"
                return (
                  <li key={alert.id} className="flex items-start gap-3 px-4 py-2.5">
                    <span className="w-10 shrink-0 pt-0.5 text-[11px] font-semibold tabular-nums text-[#607DA5]">
                      {alert.time}
                    </span>
                    {alert.image !== undefined && <DetectionThumb src={alert.image} alt={alert.title} size={36} />}
                    <div className="min-w-0 flex-1">
                      <p className="text-[12px] font-semibold leading-snug text-[#102C55]">
                        {alert.city} – {alert.title}
                      </p>
                    </div>
                    <span
                      className={cn(
                        "shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide",
                        badge
                      )}
                    >
                      {alert.severity}
                    </span>
                  </li>
                )
              })
            )}
          </ul>
        </div>

        {/* Quick actions */}
        <div className="flex min-h-[300px] flex-col overflow-hidden rounded-[10px] border border-[#D9E6F5] bg-white shadow-[0_1px_2px_rgba(16,44,85,0.04)]">
          <div className="border-b border-[#D9E6F5] px-4 py-3">
            <h2 className="inline-flex items-center gap-1.5 text-[15px] font-semibold text-[#102C55]">
              <Zap className="h-4 w-4 text-[#607DA5]" />
              Quick Actions
            </h2>
          </div>
          <div className="grid flex-1 grid-cols-1 gap-2.5 p-3 sm:grid-cols-2">
            {[
              {
                title: "View All Cameras",
                subtitle: "Live wall & camera status",
                href: ROUTES.ALL_CITIES_CAMERAS,
                icon: Camera,
                tone: "bg-[#EFF6FF] text-[#2563EB]",
              },
              {
                title: "AI Analytics",
                subtitle: "Detections & alerts",
                href: ROUTES.ANALYTICS_DASHBOARD,
                icon: BrainCircuit,
                tone: "bg-[#F5F3FF] text-[#7C3AED]",
              },
              {
                title: "Customs Operations",
                subtitle: "Seizures & detentions",
                href: ROUTES.SEIZURE_MANAGEMENT,
                icon: Shield,
                tone: "bg-[#FEF2F2] text-[#EF4444]",
              },
              {
                title: "Reports & Comparisons",
                subtitle: "PDF / Excel exports",
                href: ROUTES.REPORTS,
                icon: BarChart3,
                tone: "bg-[#EFF6FF] text-[#2563EB]",
              },
              {
                title: "Infrastructure Health",
                subtitle: "Cameras, NVRs, links",
                href: ROUTES.INFRASTRUCTURE_OVERVIEW,
                icon: Server,
                tone: "bg-[#ECFDF5] text-[#10B981]",
              },
              {
                title: "Support & Issues",
                subtitle: "Tickets & help",
                href: ROUTES.SUPPORT_DASHBOARD,
                icon: Headset,
                tone: "bg-[#F5F3FF] text-[#7C3AED]",
              },
            ].map((action) => {
              const Icon = action.icon
              return (
                <Link
                  key={action.title}
                  to={action.href}
                  className="group flex items-center gap-2.5 rounded-lg border border-[#D9E6F5] bg-white px-2.5 py-2.5 transition hover:border-[#0875E1]/40 hover:bg-[#F7FBFF]"
                >
                  <div className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-lg", action.tone)}>
                    <Icon className="h-4 w-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[12px] font-semibold text-[#102C55]">{action.title}</p>
                    <p className="truncate text-[10px] text-[#607DA5]">{action.subtitle}</p>
                  </div>
                  <ArrowRight className="h-3.5 w-3.5 shrink-0 text-[#607DA5] transition group-hover:text-[#0875E1]" />
                </Link>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
