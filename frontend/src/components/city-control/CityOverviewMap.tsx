import { useEffect, useRef } from "react"
import { MapPin } from "lucide-react"
import { GPS_DEFAULT_CENTER, loadLeaflet } from "@/components/gps/officer-gps-map"
import { cn } from "@/lib/utils"

/** Peshawar Customs Office — primary HQ pin (same as GPS default center). */
const PESHAWAR_CUSTOMS = {
  lat: GPS_DEFAULT_CENTER[0],
  lng: GPS_DEFAULT_CENTER[1],
  zoom: 15,
} as const

/** City centers for HQ read-only overview pins. */
export const CITY_COORDINATES: Record<string, { lat: number; lng: number; zoom?: number }> = {
  peshawar: { ...PESHAWAR_CUSTOMS },
  mardan: { lat: 34.198, lng: 72.04, zoom: 13 },
  nowshera: { lat: 34.015, lng: 71.975, zoom: 13 },
  kohat: { lat: 33.5889, lng: 71.4428, zoom: 13 },
  "di-khan": { lat: 31.831, lng: 70.901, zoom: 12 },
  abbottabad: { lat: 34.1463, lng: 73.2117, zoom: 13 },
  swat: { lat: 34.775, lng: 72.36, zoom: 12 },
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
}

function cityPinHtml(cityName: string, isCustoms: boolean): string {
  const label = isCustoms ? `${escapeHtml(cityName)} Customs` : escapeHtml(cityName)
  return `
    <div style="display:flex;flex-direction:column;align-items:center;width:max-content;">
      <svg width="28" height="40" viewBox="0 0 28 40" aria-hidden="true" style="display:block;filter:drop-shadow(0 1px 3px rgba(16,44,85,.35));">
        <defs>
          <linearGradient id="city-pin-grad" x1="14" y1="1" x2="14" y2="39" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stop-color="#0875E1"/>
            <stop offset="100%" stop-color="#0556A8"/>
          </linearGradient>
        </defs>
        <path fill="url(#city-pin-grad)" stroke="#fff" stroke-width="1.25"
          d="M14 1.2C7.1 1.2 1.6 7 1.6 14.3c0 8.6 10.2 22.7 12.05 24.9a.6.6 0 0 0 .7 0C16.2 37 26.4 22.9 26.4 14.3 26.4 7 20.9 1.2 14 1.2z"/>
        <circle cx="14" cy="14.2" r="5.4" fill="#fff"/>
        <circle cx="14" cy="14.2" r="2.6" fill="#0875E1"/>
      </svg>
      <span style="
        margin-top:2px;padding:2px 8px;border-radius:6px;
        background:rgba(255,255,255,.96);border:1px solid #D9E6F5;
        color:#102C55;font:700 11px Inter,Arial,sans-serif;
        white-space:nowrap;box-shadow:0 1px 2px rgba(16,44,85,.08);
      ">${label}</span>
    </div>
  `
}

type CityOverviewMapProps = {
  cityId: string
  cityName: string
  className?: string
}

export function CityOverviewMap({ cityId, cityName, className }: CityOverviewMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const coords = CITY_COORDINATES[cityId] ?? CITY_COORDINATES.peshawar
  const isCustoms = cityId === "peshawar"

  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    let cancelled = false
    let map: {
      remove: () => void
      invalidateSize: () => void
      setView: (ll: [number, number], z: number) => void
      removeLayer: (layer: unknown) => void
      scrollWheelZoom: { enable: () => void; disable: () => void }
      getContainer: () => HTMLElement
    } | null = null

    const onEnter = () => map?.scrollWheelZoom.enable()
    const onLeave = () => map?.scrollWheelZoom.disable()

    loadLeaflet()
      .then((L) => {
        if (cancelled || !containerRef.current) return

        const node = containerRef.current as HTMLDivElement & { _leaflet_id?: number }
        if (node._leaflet_id) {
          node.innerHTML = ""
        }

        map = L.map(containerRef.current, {
          zoomControl: true,
          attributionControl: false,
          // Enabled only while cursor is over the map (see mouseenter/mouseleave).
          scrollWheelZoom: false,
          doubleClickZoom: true,
          dragging: true,
        }) as typeof map

        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
          maxZoom: 18,
        }).addTo(map!)

        const center: [number, number] = [coords.lat, coords.lng]
        const zoom = coords.zoom ?? 13
        map!.setView(center, zoom)

        L.circle(center, {
          radius: isCustoms ? 350 : 1800,
          color: "#9EBDD8",
          weight: 2,
          fillColor: "#EAF3FC",
          fillOpacity: 0.45,
        }).addTo(map!)

        // Pin tip sits on the coordinates (icon is 28×40)
        const icon = L.divIcon({
          className: "city-overview-pin",
          html: cityPinHtml(cityName, isCustoms),
          iconSize: [28, 40],
          iconAnchor: [14, 40],
        })

        L.marker(center, { icon }).addTo(map!)

        const container = map!.getContainer()
        container.addEventListener("mouseenter", onEnter)
        container.addEventListener("mouseleave", onLeave)

        requestAnimationFrame(() => {
          map?.invalidateSize()
          window.setTimeout(() => map?.invalidateSize(), 180)
        })
      })
      .catch(() => {
        /* keep empty shell */
      })

    return () => {
      cancelled = true
      if (map) {
        try {
          const container = map.getContainer()
          container.removeEventListener("mouseenter", onEnter)
          container.removeEventListener("mouseleave", onLeave)
        } catch {
          /* map already torn down */
        }
        map.remove()
      }
      map = null
    }
  }, [cityId, cityName, coords.lat, coords.lng, coords.zoom, isCustoms])

  return (
    <div
      className={cn(
        "relative min-h-[180px] overflow-hidden rounded-lg border border-[#D9E6F5] bg-[#F7FBFF]",
        className
      )}
    >
      <div ref={containerRef} className="absolute inset-0 h-full w-full" />
      <div className="pointer-events-none absolute left-2 top-2 z-[500] rounded bg-white/95 px-2 py-1 text-[10px] font-semibold text-[#0875E1] shadow-sm ring-1 ring-[#D9E6F5]">
        <MapPin className="mr-1 inline h-3 w-3" />
        {isCustoms ? "Peshawar Customs" : "Location pin"}
      </div>
    </div>
  )
}
