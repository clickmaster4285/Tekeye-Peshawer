import { GPS_DEFAULT_CENTER } from "@/components/gps/officer-gps-map"

/**
 * Where each location sits on the City Status Map when no office pin is set on
 * Locations & Sync: the city centre as Google Maps shows it. Peshawar is the
 * Customs office itself. Set the exact office pin per location on Locations & Sync.
 */
export const CITY_CENTRES: Record<string, [number, number]> = {
  PESHAWAR: GPS_DEFAULT_CENTER,
  HAYATABAD: [33.9948, 71.4363],
  MARDAN: [34.1986, 72.0404],
  NOWSHERA: [34.0159, 71.9747],
  KOHAT: [33.5869, 71.4429],
  DI_KHAN: [31.8313, 70.9019],
  ABBOTTABAD: [34.1688, 73.2215],
  SWAT: [34.7717, 72.36],
  THAKOT: [34.865, 72.9165],
}

/** Map position for a location: its office pin, else the city centre, else null (not plotted). */
export function mapPosition(code: string, lat?: number | null, lng?: number | null): [number, number] | null {
  if (lat != null && lng != null) return [lat, lng]
  return CITY_CENTRES[code.toUpperCase().replace(/[\s-]+/g, "_")] ?? null
}
