import {
  fetchInfraAlerts,
  fetchInfraDevices,
  type InfraDevice,
} from "@/lib/infrastructure-api"
import {
  fetchCityControlBoard,
  type CityControlBoardCity,
} from "@/lib/ops-central-api"
import { ROUTES } from "@/routes/config"

export type CityStatus = "Online" | "Offline" | "Degraded"
export type AlertSeverity = "High" | "Critical" | "Medium" | "Info"
export type Connectivity = "Good" | "Limited" | "No Signal"

export type CityControlRow = {
  id: string
  rank: number
  city: string
  locationCode?: string
  isHq?: boolean
  status: CityStatus
  camerasOnline: number
  camerasTotal: number
  aiDetections24h: number
  seizures30d: number
  detentions30d: number
  lastSync: string
  lastSyncRelative: string
  connectivity: Connectivity
  bars: { cameras: number; ai: number; seizures: number; detentions: number }
  /** City on Locations & Sync: its cameras open straight from the city server */
  synced?: boolean
  /** Office pin from Locations & Sync (null = city centre on the map) */
  latitude?: number | null
  longitude?: number | null
}

/** Where "Cameras" goes: a synced city's own page (video direct from the city), else All Cities Cameras. */
export function cityCamerasPath(row: CityControlRow): string {
  return row.synced && !row.isHq ? `${ROUTES.CITY_CONTROL_GRID}/${row.id}/cameras` : ROUTES.ALL_CITIES_CAMERAS
}

export type CityControlKpi = {
  id: string
  label: string
  value: string
  delta?: string
  support: string
  tone: "blue" | "purple" | "red" | "orange" | "green"
}

export type CityControlAlert = {
  id: string
  time: string
  city: string
  title: string
  severity: AlertSeverity
  /** Detection picture (media path) for AI alerts */
  image?: string
}

export const CITY_CONTROL_KPIS: CityControlKpi[] = [
  {
    id: "cameras",
    label: "Total Cameras",
    value: "1,248",
    delta: "2%",
    support: "Across all cities",
    tone: "blue",
  },
  {
    id: "ai",
    label: "AI Detections (24h)",
    value: "1,892",
    delta: "12%",
    support: "People · Vehicles · Weapons · Plates",
    tone: "purple",
  },
  {
    id: "seizures",
    label: "Seizures (30d)",
    value: "124",
    delta: "8%",
    support: "All cities combined",
    tone: "red",
  },
  {
    id: "detentions",
    label: "Detentions (30d)",
    value: "87",
    delta: "5%",
    support: "All cities combined",
    tone: "orange",
  },
  {
    id: "online",
    label: "Online Cities",
    value: "5 / 7",
    support: "2 offline | 0 degraded",
    tone: "green",
  },
]

export const CITY_CONTROL_ROWS: CityControlRow[] = [
  {
    id: "peshawar",
    rank: 1,
    city: "Peshawar",
    isHq: true,
    status: "Online",
    camerasOnline: 75,
    camerasTotal: 75,
    aiDetections24h: 482,
    seizures30d: 36,
    detentions30d: 28,
    lastSync: "Oct 10, 16:09",
    lastSyncRelative: "1 min ago",
    connectivity: "Good",
    bars: { cameras: 100, ai: 100, seizures: 100, detentions: 100 },
  },
  {
    id: "mardan",
    rank: 2,
    city: "Mardan",
    status: "Online",
    camerasOnline: 62,
    camerasTotal: 62,
    aiDetections24h: 341,
    seizures30d: 22,
    detentions30d: 15,
    lastSync: "Oct 10, 16:05",
    lastSyncRelative: "5 min ago",
    connectivity: "Good",
    bars: { cameras: 100, ai: 71, seizures: 61, detentions: 54 },
  },
  {
    id: "kohat",
    rank: 3,
    city: "Kohat",
    status: "Online",
    camerasOnline: 58,
    camerasTotal: 60,
    aiDetections24h: 276,
    seizures30d: 18,
    detentions30d: 12,
    lastSync: "Oct 10, 16:03",
    lastSyncRelative: "7 min ago",
    connectivity: "Good",
    bars: { cameras: 97, ai: 57, seizures: 50, detentions: 43 },
  },
  {
    id: "di-khan",
    rank: 4,
    city: "DI Khan",
    status: "Online",
    camerasOnline: 44,
    camerasTotal: 50,
    aiDetections24h: 198,
    seizures30d: 14,
    detentions30d: 9,
    lastSync: "Oct 10, 15:58",
    lastSyncRelative: "12 min ago",
    connectivity: "Good",
    bars: { cameras: 88, ai: 41, seizures: 39, detentions: 32 },
  },
  {
    id: "nowshera",
    rank: 5,
    city: "Nowshera",
    status: "Online",
    camerasOnline: 48,
    camerasTotal: 50,
    aiDetections24h: 219,
    seizures30d: 16,
    detentions30d: 11,
    lastSync: "Oct 10, 15:53",
    lastSyncRelative: "17 min ago",
    connectivity: "Good",
    bars: { cameras: 96, ai: 45, seizures: 44, detentions: 39 },
  },
  {
    id: "abbottabad",
    rank: 6,
    city: "Abbottabad",
    status: "Offline",
    camerasOnline: 0,
    camerasTotal: 48,
    aiDetections24h: 0,
    seizures30d: 0,
    detentions30d: 0,
    lastSync: "Oct 10, 14:22",
    lastSyncRelative: "1 hr ago",
    connectivity: "No Signal",
    bars: { cameras: 0, ai: 0, seizures: 0, detentions: 0 },
  },
  {
    id: "swat",
    rank: 7,
    city: "Swat",
    status: "Degraded",
    camerasOnline: 12,
    camerasTotal: 40,
    aiDetections24h: 76,
    seizures30d: 5,
    detentions30d: 3,
    lastSync: "Oct 10, 15:21",
    lastSyncRelative: "49 min ago",
    connectivity: "Limited",
    bars: { cameras: 30, ai: 16, seizures: 14, detentions: 11 },
  },
]

export const CITY_CONTROL_ALERTS: CityControlAlert[] = [
  { id: "a1", time: "16:03", city: "Kohat", title: "AI detection: Knife weapon", severity: "High" },
  { id: "a2", time: "15:47", city: "Abbottabad", title: "Camera offline", severity: "Critical" },
  { id: "a3", time: "15:22", city: "Swat", title: "Low connectivity", severity: "Medium" },
  { id: "a4", time: "14:56", city: "Mardan", title: "Seizure recorded", severity: "Info" },
  { id: "a5", time: "13:18", city: "Peshawar", title: "New license plate detected", severity: "Info" },
]

export const CITY_MAP_MARKERS: { id: string; city: string; status: CityStatus; x: number; y: number }[] = [
  { id: "peshawar", city: "Peshawar", status: "Online", x: 38, y: 58 },
  { id: "mardan", city: "Mardan", status: "Online", x: 48, y: 42 },
  { id: "kohat", city: "Kohat", status: "Online", x: 42, y: 72 },
  { id: "di-khan", city: "DI Khan", status: "Online", x: 52, y: 88 },
  { id: "nowshera", city: "Nowshera", status: "Online", x: 44, y: 50 },
  { id: "abbottabad", city: "Abbottabad", status: "Offline", x: 72, y: 38 },
  { id: "swat", city: "Swat", status: "Degraded", x: 58, y: 22 },
]

export type CityDetectionType = "License Plate" | "Person" | "Vehicle" | "Weapon"

export type CityRecentDetection = {
  time: string
  type: CityDetectionType
  object: string
  camera: string
  image?: string
}

export type CityDetailExtras = {
  staffOnline: number
  staffTotal: number
  nvrsOnline: number
  nvrsTotal: number
  aiService: "Healthy" | "Degraded" | "Down"
  apiConnection: "Connected" | "Intermittent" | "Disconnected"
  uptime: string
  infraHealth: "Good" | "Degraded" | "Critical"
  infraOnline: number
  infraTotal: number
  infraIssues: number
  aiDelta: string
  seizureDelta: string
  detentionDelta: string
  lastSyncFull: string
  detections: CityRecentDetection[]
  trend: { day: string; people: number; vehicles: number; weapons: number; plates: number }[]
  opsBars: { day: string; seizures: number; detentions: number }[]
}

const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const

function emptyTrend(): CityDetailExtras["trend"] {
  const out: CityDetailExtras["trend"] = []
  for (let i = 6; i >= 0; i--) {
    const d = new Date()
    d.setDate(d.getDate() - i)
    out.push({ day: DAY_LABELS[d.getDay()], people: 0, vehicles: 0, weapons: 0, plates: 0 })
  }
  return out
}

function emptyOpsBars(): CityDetailExtras["opsBars"] {
  const out: CityDetailExtras["opsBars"] = []
  for (let i = 6; i >= 0; i--) {
    const d = new Date()
    d.setDate(d.getDate() - i)
    out.push({ day: DAY_LABELS[d.getDay()], seizures: 0, detentions: 0 })
  }
  return out
}

/** Fallback extras when live detail is unavailable — zeros only, no mock samples. */
export function getCityDetailExtras(city: CityControlRow): CityDetailExtras {
  const disconnected = city.status === "Offline"
  const degraded = city.status === "Degraded"
  const offlineCams = Math.max(0, city.camerasTotal - city.camerasOnline)

  return {
    staffOnline: 0,
    staffTotal: 0,
    nvrsOnline: 0,
    nvrsTotal: 0,
    aiService: disconnected ? "Down" : degraded ? "Degraded" : "Healthy",
    apiConnection: disconnected ? "Disconnected" : degraded ? "Intermittent" : "Connected",
    uptime: disconnected ? "—" : "—",
    infraHealth: disconnected ? "Critical" : degraded ? "Degraded" : "Good",
    infraOnline: city.camerasOnline > 0 ? 1 : 0,
    infraTotal: 1,
    infraIssues: offlineCams > 0 || disconnected ? 1 : 0,
    aiDelta: "—",
    seizureDelta: "—",
    detentionDelta: "—",
    lastSyncFull: city.lastSync !== "—" ? `${city.lastSync} PKT` : "—",
    detections: [],
    trend: emptyTrend(),
    opsBars: emptyOpsBars(),
  }
}

/** ——— Live City Control Grid ——— */

function slugifyCityId(code: string): string {
  return code
    .trim()
    .toLowerCase()
    .replace(/[\s_]+/g, "-")
    .replace(/[^a-z0-9-]/g, "")
}

function normalizeLocKey(raw: string): string {
  return raw.trim().toUpperCase().replace(/[\s-]+/g, "_")
}

function deviceMatchesCity(device: InfraDevice, locKey: string, cityName: string): boolean {
  const code = normalizeLocKey(device.site_code || "")
  const name = (device.site_name || "").toLowerCase()
  const install = (device.install_location || "").toLowerCase()
  const city = cityName.toLowerCase()
  return (
    code === locKey ||
    name.includes(city) ||
    install.includes(city) ||
    code.includes(locKey) ||
    locKey.includes(code)
  )
}

export type CityControlGridLive = {
  rows: CityControlRow[]
  kpis: CityControlKpi[]
  alerts: CityControlAlert[]
  extrasById: Record<string, CityDetailExtras>
}

export function zeroCityControlKpis(): CityControlKpi[] {
  return [
    { id: "cameras", label: "Total Cameras", value: "0", support: "Across all cities", tone: "blue" },
    {
      id: "ai",
      label: "AI Detections (24h)",
      value: "0",
      support: "People · Vehicles · Weapons · Plates",
      tone: "purple",
    },
    { id: "seizures", label: "Seizures (30d)", value: "0", support: "All cities combined", tone: "red" },
    { id: "detentions", label: "Detentions (30d)", value: "0", support: "All cities combined", tone: "orange" },
    { id: "online", label: "Online Cities", value: "0 / 0", support: "0 offline | 0 degraded", tone: "green" },
  ]
}

/** How often the grid and city pages refresh themselves. */
export const CITY_CONTROL_REFRESH_MS = 30_000

/** Short in-memory cache so grid ↔ summary navigation does not re-hit every API. */
let cityControlLiveCache: { at: number; data: CityControlGridLive } | null = null
const CITY_CONTROL_CACHE_MS = 45_000

function mapBoardCity(city: CityControlBoardCity): CityControlRow {
  const status = (["Online", "Offline", "Degraded"].includes(city.status)
    ? city.status
    : "Offline") as CityStatus
  const connectivity = (["Good", "Limited", "No Signal"].includes(city.connectivity)
    ? city.connectivity
    : "No Signal") as Connectivity
  return {
    id: city.id || slugifyCityId(city.location_code || city.city),
    locationCode: city.location_code || normalizeLocKey(city.city),
    rank: city.rank || 0,
    city: city.city,
    isHq: Boolean(city.is_hq),
    status,
    camerasOnline: city.cameras_online || 0,
    camerasTotal: city.cameras_total || 0,
    aiDetections24h: city.ai_detections_24h || 0,
    seizures30d: city.seizures_30d || 0,
    detentions30d: city.detentions_30d || 0,
    lastSync: city.last_sync || "—",
    lastSyncRelative: city.last_sync_relative || "No sync",
    connectivity,
    bars: city.bars || { cameras: 0, ai: 0, seizures: 0, detentions: 0 },
    synced: city.ops_source === "synced",
    latitude: city.latitude ?? null,
    longitude: city.longitude ?? null,
  }
}

const DETECTION_TYPES: CityDetectionType[] = ["License Plate", "Person", "Vehicle", "Weapon"]

/** Fill the detail page from data the city synced to this HQ (recent detections, 7-day charts). */
function withSyncedDetail(base: CityDetailExtras, city: CityControlBoardCity): CityDetailExtras {
  const detail = city.detail
  if (!detail) return base
  return {
    ...base,
    staffOnline: city.staff_online ?? base.staffOnline,
    staffTotal: city.staff_total ?? base.staffTotal,
    aiDelta: city.ai_delta || base.aiDelta,
    seizureDelta: city.seizure_delta || base.seizureDelta,
    detentionDelta: city.detention_delta || base.detentionDelta,
    detections: detail.detections.map((d) => ({
      time: d.time,
      type: (DETECTION_TYPES.includes(d.type as CityDetectionType) ? d.type : "Person") as CityDetectionType,
      object: d.object,
      camera: d.camera,
      image: d.image || undefined,
    })),
    trend: detail.trend.length ? detail.trend : base.trend,
    opsBars: detail.ops_bars.length ? detail.ops_bars : base.opsBars,
  }
}

/**
 * Federated City Control Grid.
 * Cameras + health from each registered city server; seizures / detentions / staff / AI
 * from that city's Django DB when connected in django mode.
 */
export async function fetchCityControlGridLive(opts?: {
  signal?: AbortSignal
  includeExtras?: boolean
  force?: boolean
}): Promise<CityControlGridLive> {
  const includeExtras = Boolean(opts?.includeExtras)
  if (
    !opts?.force &&
    cityControlLiveCache &&
    Date.now() - cityControlLiveCache.at < CITY_CONTROL_CACHE_MS &&
    (!includeExtras || Object.keys(cityControlLiveCache.data.extrasById).length > 0)
  ) {
    return cityControlLiveCache.data
  }

  const board = await fetchCityControlBoard({ signal: opts?.signal }).catch(() => null)
  if (opts?.signal?.aborted) {
    return { rows: [], kpis: zeroCityControlKpis(), alerts: [], extrasById: {} }
  }

  if (!board) {
    return { rows: [], kpis: zeroCityControlKpis(), alerts: [], extrasById: {} }
  }

  const rows = (board.cities || []).map(mapBoardCity)
  const kpis: CityControlKpi[] = (board.kpis || []).map((k) => ({
    id: k.id,
    label: k.label,
    value: k.value,
    support: k.support,
    tone: (["blue", "purple", "red", "orange", "green"].includes(k.tone)
      ? k.tone
      : "blue") as CityControlKpi["tone"],
    delta: k.delta,
  }))
  const alerts: CityControlAlert[] = (board.alerts || []).map((a) => ({
    id: a.id,
    time: a.time,
    city: a.city,
    title: a.title,
    severity: (["High", "Critical", "Medium", "Info"].includes(a.severity)
      ? a.severity
      : "Info") as AlertSeverity,
    // "" = AI alert whose picture has not arrived yet (placeholder shown); undefined = no picture.
    image: a.image ?? undefined,
  }))

  const extrasById: Record<string, CityDetailExtras> = {}
  for (const city of board.cities || []) {
    if (city.detail) {
      const row = mapBoardCity(city)
      extrasById[row.id] = withSyncedDetail(getCityDetailExtras(row), city)
    }
  }

  if (includeExtras) {
    const [infraDevices] = await Promise.all([
      fetchInfraDevices().catch(() => [] as InfraDevice[]),
      fetchInfraAlerts({ resolved: false }).catch(() => []),
    ])

    for (const city of board.cities || []) {
      const row = mapBoardCity(city)
      const locKey = row.locationCode || normalizeLocKey(row.city)
      const devices = infraDevices.filter((d) => deviceMatchesCity(d, locKey, row.city))
      const nvrs = devices.filter((d) => d.device_type === "nvr")
      const nvrsOnline = nvrs.filter((d) => d.status === "online").length
      const onlineDevices = devices.filter((d) => d.status === "online").length
      const issueDevices = devices.filter(
        (d) => d.status !== "online" && d.status !== "maintenance"
      ).length

      let infraHealth: CityDetailExtras["infraHealth"] = "Good"
      if (row.status === "Offline" || (devices.length > 0 && onlineDevices === 0)) {
        infraHealth = "Critical"
      } else if (row.status === "Degraded" || issueDevices > 0) {
        infraHealth = "Degraded"
      }

      const base = extrasById[row.id] ?? getCityDetailExtras(row)
      extrasById[row.id] = {
        ...base,
        staffOnline: city.staff_online ?? 0,
        staffTotal: city.staff_total ?? 0,
        nvrsOnline,
        nvrsTotal: nvrs.length,
        infraHealth,
        infraOnline: devices.length ? onlineDevices : row.camerasOnline > 0 ? 1 : 0,
        infraTotal: devices.length || 1,
        infraIssues: issueDevices || Math.max(0, row.camerasTotal - row.camerasOnline),
      }
    }
  }

  const result: CityControlGridLive = {
    rows,
    kpis: kpis.length ? kpis : zeroCityControlKpis(),
    alerts,
    extrasById,
  }
  cityControlLiveCache = { at: Date.now(), data: result }
  return result
}
