import { useEffect, useMemo, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  ArrowUpRight,
  BarChart3,
  BrainCircuit,
  Camera,
  Car,
  Download,
  FileSpreadsheet,
  FileText,
  LayoutDashboard,
  LayoutGrid,
  MapPin,
  Search,
  Server,
  Shield,
  UserRound,
  Users,
} from "lucide-react"
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { CityOverviewMap } from "@/components/city-control/CityOverviewMap"
import {
  fetchCityControlGridLive,
  getCityDetailExtras,
  type CityControlRow,
  type CityDetailExtras,
  type CityDetectionType,
  type CityStatus,
} from "@/data/city-control-grid-data"
import { ROUTES } from "@/routes/config"
import { cn } from "@/lib/utils"

const STATUS_COLOR: Record<CityStatus, string> = {
  Online: "#12A66A",
  Offline: "#FF4D59",
  Degraded: "#FF9D2E",
}

const NAV_ITEMS = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "cameras", label: "Cameras", icon: Camera },
  { id: "ai", label: "AI Detections", icon: BrainCircuit },
  { id: "seizures", label: "Seizures & Detentions", icon: Shield },
  { id: "customs", label: "Customs Operations", icon: FileText },
  { id: "infra", label: "Infrastructure", icon: Server },
  { id: "charts", label: "Charts & Reports", icon: BarChart3 },
] as const

type NavId = (typeof NAV_ITEMS)[number]["id"]

function detectionIcon(type: CityDetectionType) {
  switch (type) {
    case "License Plate":
      return <Car className="h-3.5 w-3.5 text-[#0875E1]" />
    case "Person":
      return <UserRound className="h-3.5 w-3.5 text-[#7552E8]" />
    case "Vehicle":
      return <Car className="h-3.5 w-3.5 text-[#12A66A]" />
    case "Weapon":
      return <AlertTriangle className="h-3.5 w-3.5 text-[#FF4D59]" />
  }
}

function StatusPill({ status }: { status: CityStatus }) {
  const color = STATUS_COLOR[status]
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-semibold"
      style={{ color, borderColor: `${color}55`, backgroundColor: `${color}12` }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: color }} />
      {status}
    </span>
  )
}

function CityPickerCard({
  city,
  extras,
  active,
  onSelect,
}: {
  city: CityControlRow
  extras: CityDetailExtras
  active: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "min-w-[150px] flex-1 rounded-[10px] border bg-white px-3 py-2.5 text-left transition",
        active
          ? "border-[#0875E1] shadow-[0_0_0_1px_#0875E1]"
          : "border-[#D9E6F5] hover:border-[#0875E1]/50"
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5">
          <MapPin className="h-3.5 w-3.5 shrink-0 text-[#0875E1]" />
          <span className="truncate text-[13px] font-semibold text-[#102C55]">{city.city}</span>
        </div>
        <StatusPill status={city.status} />
      </div>
      <div className="mt-2 space-y-1 text-[11px] text-[#607DA5]">
        <p className="flex items-center gap-1.5">
          <Camera className="h-3 w-3" />
          {city.camerasOnline}/{city.camerasTotal}
        </p>
        <p className="flex items-center gap-1.5">
          <AlertTriangle className="h-3 w-3" />
          {city.aiDetections24h}
        </p>
        <p className="flex items-center gap-1.5">
          <Shield className="h-3 w-3" />
          {city.seizures30d}
        </p>
        <p className="flex items-center gap-1.5">
          <Users className="h-3 w-3" />
          {extras.staffOnline}/{extras.staffTotal}
        </p>
      </div>
    </button>
  )
}

export default function CityControlSummaryPage() {
  const { cityId = "" } = useParams()
  const navigate = useNavigate()
  const [query, setQuery] = useState("")
  const [section, setSection] = useState<NavId>("overview")
  const [rows, setRows] = useState<CityControlRow[]>([])
  const [extrasById, setExtrasById] = useState<Record<string, CityDetailExtras>>({})
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const ac = new AbortController()
    setLoading(true)
    fetchCityControlGridLive({ signal: ac.signal, includeExtras: true })
      .then((live) => {
        if (ac.signal.aborted) return
        setRows(live.rows)
        setExtrasById(live.extrasById)
      })
      .catch(() => {
        if (ac.signal.aborted) return
        setRows([])
        setExtrasById({})
      })
      .finally(() => {
        if (!ac.signal.aborted) setLoading(false)
      })
    return () => ac.abort()
  }, [])

  const city = rows.find((c) => c.id === cityId)

  const pickerCities = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return rows
    return rows.filter((c) => c.city.toLowerCase().includes(q))
  }, [query, rows])

  if (loading) {
    return (
      <div className="rounded-[10px] border border-[#D9E6F5] bg-white p-6">
        <p className="text-sm text-[#607DA5]">Loading live city analytics…</p>
      </div>
    )
  }

  if (!city) {
    return (
      <div className="rounded-[10px] border border-[#D9E6F5] bg-white p-6">
        <p className="text-sm text-[#607DA5]">City not found.</p>
        <Link to={ROUTES.CITY_CONTROL_GRID} className="mt-3 inline-flex text-sm font-semibold text-[#0875E1]">
          Back to City Control Grid
        </Link>
      </div>
    )
  }

  const extras = extrasById[city.id] || getCityDetailExtras(city)
  const camerasOffline = city.camerasTotal - city.camerasOnline
  const isStale = city.status === "Offline"

  return (
    <div className="flex w-full min-w-0 max-w-full flex-col gap-4">
      {/* Page header + search */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="flex items-start gap-2.5">
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#F5F3FF]">
            <LayoutGrid className="h-[18px] w-[18px] text-[#7C3AED]" />
          </div>
          <div>
            <h1 className="text-[22px] font-bold tracking-tight text-[#102C55]">City Control Grid</h1>
            <p className="mt-0.5 text-[13px] text-[#607DA5]">
              Read-only city analytics · select a city card or use View from the grid
            </p>
          </div>
        </div>
        <label className="relative block w-full sm:w-[240px]">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#607DA5]" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search city..."
            className="h-9 w-full rounded-lg border border-[#D9E6F5] bg-white pl-8 pr-3 text-[13px] text-[#102C55] outline-none placeholder:text-[#90A7C4] focus:border-[#0875E1] focus:ring-2 focus:ring-[#0875E1]/20"
          />
        </label>
      </div>

      {/* City cards strip */}
      <div id="city-picker-strip" className="flex gap-3 overflow-x-auto pb-1">
        {pickerCities.map((c) => (
          <CityPickerCard
            key={c.id}
            city={c}
            extras={extrasById[c.id] || getCityDetailExtras(c)}
            active={c.id === city.id}
            onSelect={() => navigate(`${ROUTES.CITY_CONTROL_GRID}/${c.id}`)}
          />
        ))}
      </div>

      {/* Detail header */}
      <div className="flex flex-col gap-3 rounded-[10px] border border-[#D9E6F5] bg-white px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-[18px] font-bold text-[#102C55]">
              {city.city} City — City Level Summary (Read Only)
            </h2>
            <StatusPill status={city.status} />
          </div>
          <p className="mt-1 text-[12px] text-[#607DA5]">
            Last Sync: {extras.lastSyncFull} ({city.lastSyncRelative})
            {isStale ? <span className="ml-1 font-semibold text-[#FF4D59]">· Not live</span> : null}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() =>
              document.getElementById("city-picker-strip")?.scrollIntoView({ behavior: "smooth", block: "start" })
            }
            className="h-9 rounded-lg bg-[#0875E1] px-3 text-[12px] font-semibold text-white hover:bg-[#086BC6]"
          >
            View Other Cities
          </button>
          <Link
            to={ROUTES.CITY_CONTROL_GRID}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#D9E6F5] bg-white px-3 text-[12px] font-semibold text-[#102C55] hover:bg-[#F4F8FD]"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to City Grid
          </Link>
        </div>
      </div>

      {/* Body: sidebar + content */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[200px_minmax(0,1fr)]">
        <aside className="h-fit rounded-[10px] border border-[#D9E6F5] bg-white p-2">
          <nav className="space-y-0.5">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon
              const active = section === item.id
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setSection(item.id)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[12px] font-medium transition",
                    active
                      ? "bg-[#0875E1] text-white"
                      : "text-[#607DA5] hover:bg-[#F4F8FD] hover:text-[#102C55]"
                  )}
                >
                  <Icon className="h-3.5 w-3.5 shrink-0" />
                  {item.label}
                </button>
              )
            })}
          </nav>
        </aside>

        <div className="min-w-0 space-y-4">
          {/* KPI row */}
          <div className="grid grid-cols-2 gap-3 xl:grid-cols-5">
            <div className="rounded-[10px] border border-[#BFDBFE] bg-white p-3">
              <div className="flex items-start justify-between">
                <p className="text-[12px] font-medium text-[#607DA5]">Total Cameras</p>
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#EFF6FF]">
                  <Camera className="h-4 w-4 text-[#2563EB]" />
                </div>
              </div>
              <p className="mt-1 text-[24px] font-bold text-[#102C55]">
                {city.camerasOnline}/{city.camerasTotal}
              </p>
              <p className={cn("mt-1 text-[11px]", camerasOffline ? "font-medium text-[#FF4D59]" : "text-[#607DA5]")}>
                {camerasOffline ? `${camerasOffline} offline` : "All online"}
              </p>
            </div>

            <div className="rounded-[10px] border border-[#DDD6FE] bg-white p-3">
              <div className="flex items-start justify-between">
                <p className="text-[12px] font-medium text-[#607DA5]">AI Detections (24h)</p>
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#F5F3FF]">
                  <BrainCircuit className="h-4 w-4 text-[#7C3AED]" />
                </div>
              </div>
              <div className="mt-1 flex items-end gap-2">
                <p className="text-[24px] font-bold text-[#102C55]">{city.aiDetections24h}</p>
                <span className="mb-1 inline-flex items-center gap-0.5 text-[11px] font-semibold text-[#12A66A]">
                  <ArrowUpRight className="h-3 w-3" />
                  {extras.aiDelta}
                </span>
              </div>
              <p className="mt-1 text-[11px] text-[#607DA5]">People · Vehicles · Weapons · Plates</p>
            </div>

            <div className="rounded-[10px] border border-[#FECACA] bg-white p-3">
              <div className="flex items-start justify-between">
                <p className="text-[12px] font-medium text-[#607DA5]">Seizures (30d)</p>
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#FEF2F2]">
                  <Shield className="h-4 w-4 text-[#EF4444]" />
                </div>
              </div>
              <div className="mt-1 flex items-end gap-2">
                <p className="text-[24px] font-bold text-[#102C55]">{city.seizures30d}</p>
                <span className="mb-1 inline-flex items-center gap-0.5 text-[11px] font-semibold text-[#12A66A]">
                  <ArrowUpRight className="h-3 w-3" />
                  {extras.seizureDelta}
                </span>
              </div>
              <p className="mt-1 text-[11px] text-[#607DA5]">Local city records</p>
            </div>

            <div className="rounded-[10px] border border-[#FED7AA] bg-white p-3">
              <div className="flex items-start justify-between">
                <p className="text-[12px] font-medium text-[#607DA5]">Detentions (30d)</p>
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#FFF7ED]">
                  <UserRound className="h-4 w-4 text-[#F59E0B]" />
                </div>
              </div>
              <div className="mt-1 flex items-end gap-2">
                <p className="text-[24px] font-bold text-[#102C55]">{city.detentions30d}</p>
                <span className="mb-1 inline-flex items-center gap-0.5 text-[11px] font-semibold text-[#12A66A]">
                  <ArrowUpRight className="h-3 w-3" />
                  {extras.detentionDelta}
                </span>
              </div>
              <p className="mt-1 text-[11px] text-[#607DA5]">Local city records</p>
            </div>

            <div className="rounded-[10px] border border-[#A7F3D0] bg-white p-3">
              <div className="flex items-start justify-between">
                <p className="text-[12px] font-medium text-[#607DA5]">Infrastructure Health</p>
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#ECFDF5]">
                  <Server className="h-4 w-4 text-[#10B981]" />
                </div>
              </div>
              <p
                className="mt-1 text-[24px] font-bold"
                style={{
                  color:
                    extras.infraHealth === "Good"
                      ? "#12A66A"
                      : extras.infraHealth === "Degraded"
                        ? "#FF9D2E"
                        : "#FF4D59",
                }}
              >
                {extras.infraHealth}
              </p>
              <p className="mt-1 text-[11px] text-[#607DA5]">
                {extras.infraOnline}/{extras.infraTotal} online
                {extras.infraIssues ? ` | ${extras.infraIssues} issue${extras.infraIssues > 1 ? "s" : ""}` : ""}
              </p>
            </div>
          </div>

          {/* Middle: overview + detections */}
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <div className="rounded-[10px] border border-[#D9E6F5] bg-white p-4">
              <h3 className="text-[14px] font-semibold text-[#102C55]">City Overview</h3>
              <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
                <CityOverviewMap cityId={city.id} cityName={city.city} className="min-h-[200px] sm:min-h-[220px]" />

                <div>
                  <p className="mb-2 text-[12px] font-semibold text-[#102C55]">Quick Status</p>
                  <ul className="divide-y divide-[#E8F0FA] rounded-lg border border-[#D9E6F5] text-[12px]">
                    {[
                      ["API Connection", extras.apiConnection],
                      ["Last Sync", city.lastSyncRelative],
                      ["Cameras", `${city.camerasOnline} / ${city.camerasTotal}`],
                      ["NVRs", `${extras.nvrsOnline} / ${extras.nvrsTotal}`],
                      ["AI Service", extras.aiService],
                      ["Connectivity", city.connectivity],
                      ["Uptime", extras.uptime],
                    ].map(([label, value]) => (
                      <li key={label} className="flex items-center justify-between gap-2 px-2.5 py-1.5">
                        <span className="text-[#607DA5]">{label}</span>
                        <span
                          className={cn(
                            "font-semibold text-[#102C55]",
                            (value === "Disconnected" || value === "Down" || value === "No Signal") &&
                              "text-[#FF4D59]",
                            (value === "Intermittent" || value === "Degraded" || value === "Limited") &&
                              "text-[#FF9D2E]",
                            (value === "Connected" || value === "Healthy" || value === "Good") && "text-[#12A66A]"
                          )}
                        >
                          {value}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>

            <div className="rounded-[10px] border border-[#D9E6F5] bg-white p-4">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-[14px] font-semibold text-[#102C55]">
                  Recent AI Detections ({city.city})
                </h3>
                <Activity className="h-4 w-4 text-[#607DA5]" />
              </div>
              {extras.detections.length === 0 ? (
                <p className="mt-8 text-center text-[13px] text-[#607DA5]">
                  No live detections — city is offline. Showing last known snapshot only.
                </p>
              ) : (
                <div className="mt-3 overflow-x-auto">
                  <table className="w-full text-left text-[12px]">
                    <thead>
                      <tr className="border-b border-[#E8F0FA] text-[#607DA5]">
                        <th className="py-2 pr-2 font-semibold">Time</th>
                        <th className="py-2 pr-2 font-semibold">Type</th>
                        <th className="py-2 pr-2 font-semibold">Object</th>
                        <th className="py-2 font-semibold">Camera</th>
                      </tr>
                    </thead>
                    <tbody>
                      {extras.detections.map((row) => (
                        <tr key={`${row.time}-${row.object}`} className="border-b border-[#F2F7FC]">
                          <td className="py-2 pr-2 tabular-nums text-[#607DA5]">{row.time}</td>
                          <td className="py-2 pr-2">
                            <span className="inline-flex items-center gap-1.5 font-medium text-[#102C55]">
                              {detectionIcon(row.type)}
                              {row.type}
                            </span>
                          </td>
                          <td className="py-2 pr-2 font-medium text-[#102C55]">{row.object}</td>
                          <td className="py-2 text-[#607DA5]">{row.camera}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>

          {/* Charts + reports */}
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
            <div className="rounded-[10px] border border-[#D9E6F5] bg-white p-4 xl:col-span-1">
              <h3 className="text-[14px] font-semibold text-[#102C55]">Detections Trend (Last 7 Days)</h3>
              <div className="mt-3 h-[220px]">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={extras.trend}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#E8F0FA" />
                    <XAxis dataKey="day" tick={{ fontSize: 11, fill: "#607DA5" }} />
                    <YAxis tick={{ fontSize: 11, fill: "#607DA5" }} />
                    <Tooltip />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Line type="monotone" dataKey="people" stroke="#7552E8" strokeWidth={2} dot={false} />
                    <Line type="monotone" dataKey="vehicles" stroke="#0875E1" strokeWidth={2} dot={false} />
                    <Line type="monotone" dataKey="weapons" stroke="#FF4D59" strokeWidth={2} dot={false} />
                    <Line type="monotone" dataKey="plates" stroke="#12A66A" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="rounded-[10px] border border-[#D9E6F5] bg-white p-4">
              <h3 className="text-[14px] font-semibold text-[#102C55]">Seizures & Detentions (Last 7 Days)</h3>
              <div className="mt-3 h-[220px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={extras.opsBars}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#E8F0FA" />
                    <XAxis dataKey="day" tick={{ fontSize: 11, fill: "#607DA5" }} />
                    <YAxis tick={{ fontSize: 11, fill: "#607DA5" }} />
                    <Tooltip />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Bar dataKey="seizures" fill="#FF4D59" radius={[3, 3, 0, 0]} />
                    <Bar dataKey="detentions" fill="#FF9D2E" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="rounded-[10px] border border-[#D9E6F5] bg-white p-4">
              <h3 className="text-[14px] font-semibold text-[#102C55]">History & Reports</h3>
              <ul className="mt-3 space-y-2">
                {[
                  { title: "Daily Snapshot (PDF)", icon: FileText },
                  { title: "Export Data (Excel)", icon: FileSpreadsheet },
                  { title: "Comparative Report", icon: BarChart3 },
                ].map((item) => {
                  const Icon = item.icon
                  return (
                    <li key={item.title}>
                      <button
                        type="button"
                        className="flex w-full items-center gap-2.5 rounded-lg border border-[#D9E6F5] px-3 py-2.5 text-left transition hover:border-[#0875E1]/40 hover:bg-[#F7FBFF]"
                      >
                        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#EFF6FF]">
                          <Icon className="h-4 w-4 text-[#0875E1]" />
                        </div>
                        <span className="flex-1 text-[12px] font-semibold text-[#102C55]">{item.title}</span>
                        <Download className="h-3.5 w-3.5 text-[#607DA5]" />
                      </button>
                    </li>
                  )
                })}
              </ul>
            </div>
          </div>

          {/* Section note for non-overview tabs */}
          {section !== "overview" ? (
            <div className="rounded-[10px] border border-[#D9E6F5] bg-[#F7FBFF] px-4 py-3 text-[13px] text-[#607DA5]">
              Showing <span className="font-semibold text-[#102C55]">{NAV_ITEMS.find((n) => n.id === section)?.label}</span>{" "}
              context for {city.city}. Full module deep-links stay on the local city system; this HQ view remains
              read-only analytics.
            </div>
          ) : null}

          {/* Footer disclaimer */}
          <div className="rounded-[10px] border border-[#BFDBFE] bg-[#EFF6FF] px-4 py-3 text-[12px] leading-relaxed text-[#355D8A]">
            <strong className="text-[#102C55]">Federated read-only view.</strong> Each city owns its operational
            database. HQ pulls live summary totals (cameras, seizures, detentions, staff, AI) from that city’s Django
            when connected. Offline cities show last-known snapshots and are never labeled as live. Sensitive case
            details are not copied into the HQ database.
          </div>
        </div>
      </div>

    </div>
  )
}
