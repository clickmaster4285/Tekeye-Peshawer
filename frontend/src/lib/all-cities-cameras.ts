export const ALL_CITIES_CAMERAS_KEY = "tekeye_all_cities_cameras"
export const ALL_CITIES_CAMERAS_EVENT = "all-cities-cameras-changed"
export const ALL_CITIES_STREAMS_CACHE_KEY = "tekeye_all_cities_streams_cache"

export type AllCitiesStreamsCache = {
  servers: unknown[]
  cameras: unknown[]
  fetchedAt: number
}

export function getAllCitiesCameras(): boolean {
  try {
    return sessionStorage.getItem(ALL_CITIES_CAMERAS_KEY) === "1"
  } catch {
    return false
  }
}

export function setAllCitiesCamerasPreference(enabled: boolean): void {
  try {
    sessionStorage.setItem(ALL_CITIES_CAMERAS_KEY, enabled ? "1" : "0")
  } catch {
    /* ignore */
  }
  window.dispatchEvent(
    new CustomEvent(ALL_CITIES_CAMERAS_EVENT, { detail: { enabled } }),
  )
}

export function readAllCitiesStreamsCache(): AllCitiesStreamsCache | null {
  try {
    const raw = sessionStorage.getItem(ALL_CITIES_STREAMS_CACHE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as AllCitiesStreamsCache
    if (!parsed || !Array.isArray(parsed.servers) || !Array.isArray(parsed.cameras)) {
      return null
    }
    return parsed
  } catch {
    return null
  }
}

export function writeAllCitiesStreamsCache(servers: unknown[], cameras: unknown[]): void {
  try {
    const payload: AllCitiesStreamsCache = {
      servers,
      cameras,
      fetchedAt: Date.now(),
    }
    sessionStorage.setItem(ALL_CITIES_STREAMS_CACHE_KEY, JSON.stringify(payload))
  } catch {
    /* ignore */
  }
}
