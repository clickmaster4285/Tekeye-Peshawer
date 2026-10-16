/**
 * Locations & Sync API (HQ only) — add city servers, test the link, pause, and pull full history.
 * Backend: backend/city_sync/sites_api.py
 */
import { API_BASE_URL, getAuthHeaders } from "@/lib/api"

const BASE = `${API_BASE_URL}/api/sync/v1/sites`

export type SyncSiteState =
  | "ONLINE"
  | "DEGRADED"
  | "OFFLINE"
  | "LONG_OFFLINE"
  | "PAUSED"
  | "UNKNOWN"

export type SyncSite = {
  location_code: string
  name: string
  base_url: string
  is_paused: boolean
  state: SyncSiteState
  heartbeat_age_sec: number | null
  last_heartbeat_at: string | null
  app_version: string
  pending_outbox: number
  dead_outbox: number
  pending_media: number
  failed_media: number
  disk_percent: number | null
  records_received: number
  media_received: number
  full_history: "NONE" | "REQUESTED" | "DONE"
  full_history_requested_at: string | null
  full_history_done_at: string | null
  last_test_at: string | null
  last_test_ok: boolean | null
  last_test_detail: string
  /** HQ -> city HR changes (Stage 4) */
  downlink_pending: number
  downlink_failed: number
  downlink_last_error: string
  created_at: string
}

export type SyncSitesResponse = {
  hq: { location_code: string; public_url: string }
  sites: SyncSite[]
  unregistered: string[]
  location_options: { code: string; label: string }[]
}

/** Returned once when a site is added or its key is replaced. */
export type SyncSiteKey = { api_key: string; env_snippet: string }

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, { ...init, headers: getAuthHeaders() })
  if (res.status === 204) return undefined as T
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = (data as { detail?: string })?.detail
    throw new Error(detail || `Request failed (HTTP ${res.status})`)
  }
  return data as T
}

const siteUrl = (code: string) => `${BASE}/${encodeURIComponent(code)}/`

export function fetchSyncSites(): Promise<SyncSitesResponse> {
  return request(`${BASE}/`)
}

export function addSyncSite(body: {
  location_code: string
  name: string
  base_url: string
}): Promise<{ site: SyncSite } & SyncSiteKey> {
  return request(`${BASE}/`, { method: "POST", body: JSON.stringify(body) })
}

export function updateSyncSite(
  code: string,
  body: Partial<Pick<SyncSite, "name" | "base_url" | "is_paused">>
): Promise<{ site: SyncSite }> {
  return request(siteUrl(code), { method: "PATCH", body: JSON.stringify(body) })
}

export function removeSyncSite(code: string): Promise<void> {
  return request(siteUrl(code), { method: "DELETE" })
}

export function rotateSyncSiteKey(code: string): Promise<SyncSiteKey> {
  return request(`${siteUrl(code)}rotate-key/`, { method: "POST" })
}

export function testSyncSite(code: string): Promise<{ ok: boolean; detail: string; site: SyncSite }> {
  return request(`${siteUrl(code)}test/`, { method: "POST" })
}

export function requestFullHistory(code: string): Promise<{ site: SyncSite }> {
  return request(`${siteUrl(code)}full-history/`, { method: "POST" })
}
