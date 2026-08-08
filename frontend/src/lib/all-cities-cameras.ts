export const ALL_CITIES_CAMERAS_KEY = "tekeye_all_cities_cameras"
export const ALL_CITIES_CAMERAS_EVENT = "all-cities-cameras-changed"

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
