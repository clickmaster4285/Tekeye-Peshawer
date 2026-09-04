import { normalizeRole } from "@/lib/role-access"

export const ALL_CITIES_CAMERAS_KEY = "tekeye_all_cities_cameras"
export const ALL_CITIES_CAMERAS_EVENT = "all-cities-cameras-changed"

/** Roles that can open All Cities Cameras (admin + collectorate side + IT ops). */
const ALL_CITIES_VIEWER_ROLES = new Set([
  "ADMIN",
  "IT_SUPERADMIN",
  "COLLECTOR",
  "DEPUTY_COLLECTOR",
  "ASSISTANT_COLLECTOR",
])

export function canViewAllCitiesCameras(role: string | undefined | null): boolean {
  const normalized = normalizeRole(role)
  return Boolean(normalized && ALL_CITIES_VIEWER_ROLES.has(normalized))
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
    const next = enabled ? "1" : "0"
    const prev = sessionStorage.getItem(ALL_CITIES_CAMERAS_KEY)
    if (prev === next) return
    sessionStorage.setItem(ALL_CITIES_CAMERAS_KEY, next)
  } catch {
    /* ignore */
  }
  window.dispatchEvent(
    new CustomEvent(ALL_CITIES_CAMERAS_EVENT, { detail: { enabled } }),
  )
}
