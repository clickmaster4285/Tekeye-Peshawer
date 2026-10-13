export type CityStatus = "Online" | "Offline" | "Degraded"
export type AlertSeverity = "High" | "Critical" | "Medium" | "Info"
export type Connectivity = "Good" | "Limited" | "No Signal"

export type CityControlRow = {
  id: string
  rank: number
  city: string
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

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

function scaleTrend(base: number) {
  return DAYS.map((day, i) => {
    const f = 0.55 + ((i * 17 + base) % 40) / 100
    return {
      day,
      people: Math.round(base * 0.12 * f),
      vehicles: Math.round(base * 0.09 * f),
      weapons: Math.max(0, Math.round(base * 0.015 * f)),
      plates: Math.round(base * 0.07 * f),
    }
  })
}

function scaleOps(seizures: number, detentions: number) {
  return DAYS.map((day, i) => ({
    day,
    seizures: Math.max(0, Math.round((seizures / 7) * (0.6 + (i % 4) * 0.2))),
    detentions: Math.max(0, Math.round((detentions / 7) * (0.5 + (i % 3) * 0.25))),
  }))
}

const DETECTION_TEMPLATES: CityRecentDetection[] = [
  { time: "16:03", type: "Weapon", object: "Knife", camera: "Cam 12" },
  { time: "15:47", type: "License Plate", object: "LES-4521", camera: "Cam 03" },
  { time: "15:22", type: "Person", object: "Unrecognized", camera: "Cam 07" },
  { time: "14:58", type: "Vehicle", object: "SUV", camera: "Cam 01" },
  { time: "14:11", type: "License Plate", object: "BXV-742", camera: "Cam 09" },
]

export function getCityDetailExtras(city: CityControlRow): CityDetailExtras {
  const offline = city.camerasTotal - city.camerasOnline
  const disconnected = city.status === "Offline"
  const degraded = city.status === "Degraded"

  return {
    staffOnline: disconnected ? 0 : Math.max(1, Math.round(city.camerasOnline / 12)),
    staffTotal: Math.max(3, Math.round(city.camerasTotal / 12)),
    nvrsOnline: disconnected ? 0 : degraded ? 2 : Math.max(1, Math.ceil(city.camerasOnline / 15)),
    nvrsTotal: Math.max(2, Math.ceil(city.camerasTotal / 15)),
    aiService: disconnected ? "Down" : degraded ? "Degraded" : "Healthy",
    apiConnection: disconnected ? "Disconnected" : degraded ? "Intermittent" : "Connected",
    uptime: disconnected ? "—" : degraded ? "94.2%" : "99.7%",
    infraHealth: disconnected ? "Critical" : degraded ? "Degraded" : "Good",
    infraOnline: disconnected ? 0 : degraded ? 3 : 4,
    infraTotal: 5,
    infraIssues: disconnected ? 5 : degraded ? 2 : offline > 0 ? 1 : 0,
    aiDelta: disconnected ? "0%" : "12%",
    seizureDelta: disconnected ? "0%" : "8%",
    detentionDelta: disconnected ? "0%" : "5%",
    lastSyncFull: `${city.lastSync} PKT`,
    detections: disconnected
      ? []
      : DETECTION_TEMPLATES.map((d, i) => ({
          ...d,
          camera: `Cam ${String(((city.rank + i) % 12) + 1).padStart(2, "0")}`,
        })),
    trend: scaleTrend(Math.max(20, city.aiDetections24h)),
    opsBars: scaleOps(city.seizures30d, city.detentions30d),
  }
}
