/**
 * Analytics Dashboard API — every number comes from HQ's database (its own data plus what
 * cities synced). Backend: backend/ops_central/analytics.py
 */
import { API_BASE_URL, getAuthHeaders } from "@/lib/api"

export const ALL_LOCATIONS = "ALL"

export type Severity = "Critical" | "High" | "Medium" | "Low"
export type DetectionKind = "Person" | "Vehicle" | "Weapon" | "License Plate" | "Other"

export type AnalyticsQuery = { location: string; from: string; to: string }

export type AnalyticsDetection = {
  id: number
  time: string
  at: string
  type: DetectionKind | string
  object: string
  camera: string
  image: string
  location_code: string
  location: string
  severity: Severity
  is_alert: boolean
}

export type AnalyticsData = {
  generated_at: string
  scope: string
  range: { from: string; to: string; bucket: "hour" | "day" }
  locations: { code: string; name: string; status: string; is_hq: boolean }[]
  overview: {
    alerts_by_severity: { critical: number; high: number; medium: number; low: number }
    incidents_today: number
    cameras_online: number
    cameras_offline: number
    cameras_total: number
    locations_online: number
    locations_total: number
    ai_processing: "online" | "offline"
    storage_percent: number | null
    system_health: number | null
  }
  stats: {
    people: number
    vehicles: number
    weapons: number
    plates: number
    total: number
    face_matches: number
    blacklist_encounters: number
  }
  by_class: { name: string; count: number }[]
  top_alert_cameras: { camera: string; location: string; count: number }[]
  over_time: { label: string; people: number; vehicles: number; weapons: number; plates: number; other: number }[]
  activity_by_hour: { label: string; count: number }[]
  activity_by_weekday: { label: string; count: number }[]
  confidence_trend: { label: string; avg_confidence: number; count: number }[]
  alerts: AnalyticsDetection[]
  map: {
    code: string
    name: string
    status: string
    cameras_online: number
    cameras_total: number
    ai_detections_24h: number
    is_hq: boolean
  }[]
}

export type EventLogQuery = AnalyticsQuery & {
  q: string
  severities: Severity[]
  types: DetectionKind[]
  page: number
}

export type EventLogPage = {
  count: number
  page: number
  page_size: number
  results: (AnalyticsDetection & { confidence: number })[]
}

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(url, { headers: getAuthHeaders(), signal })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error((data as { detail?: string })?.detail || `Request failed (HTTP ${res.status})`)
  return data as T
}

export function fetchAnalytics(query: AnalyticsQuery, signal?: AbortSignal): Promise<AnalyticsData> {
  const params = new URLSearchParams({ location: query.location, from: query.from, to: query.to })
  return getJson(`${API_BASE_URL}/api/ops/analytics/?${params}`, signal)
}

export function fetchEventLog(query: EventLogQuery, signal?: AbortSignal): Promise<EventLogPage> {
  const params = new URLSearchParams({
    location: query.location,
    from: query.from,
    to: query.to,
    page: String(query.page),
  })
  if (query.q.trim()) params.set("q", query.q.trim())
  if (query.severities.length) params.set("severity", query.severities.join(","))
  if (query.types.length) params.set("type", query.types.join(","))
  return getJson(`${API_BASE_URL}/api/ops/analytics/events/?${params}`, signal)
}
