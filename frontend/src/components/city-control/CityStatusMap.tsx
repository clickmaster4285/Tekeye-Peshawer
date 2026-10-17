import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { loadLeaflet } from "@/components/gps/officer-gps-map"
import { type CityControlRow, type CityStatus } from "@/data/city-control-grid-data"
import { ROUTES } from "@/routes/config"
import { cn } from "@/lib/utils"
import { mapPosition } from "./city-map-positions"

type Leaflet = Awaited<ReturnType<typeof loadLeaflet>>
type LeafletMap = ReturnType<Leaflet["map"]>
type LeafletMarker = ReturnType<Leaflet["marker"]>

const STATUS_COLOR: Record<CityStatus, string> = {
  Online: "#0ca30c",
  Degraded: "#fab219",
  Offline: "#d03b3b",
}

const LEGEND: CityStatus[] = ["Online", "Degraded", "Offline"]

function escapeHtml(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;")
}

/** Status dot + label card; the status is written out, never shown by colour alone. */
function pinHtml(row: CityControlRow): string {
  const color = STATUS_COLOR[row.status] ?? STATUS_COLOR.Offline
  return `
    <div style="display:flex;align-items:center;gap:6px;width:max-content;transform:translate(-9px,-9px);cursor:pointer;">
      <span style="position:relative;display:block;width:18px;height:18px;">
        <span style="position:absolute;inset:-5px;border-radius:50%;background:${color};opacity:.22;"></span>
        <span style="position:absolute;inset:0;border-radius:50%;background:${color};border:2px solid #fff;box-shadow:0 1px 3px rgba(16,44,85,.4);"></span>
      </span>
      <span style="padding:3px 8px;border-radius:6px;background:rgba(255,255,255,.97);border:1px solid #D9E6F5;
        box-shadow:0 1px 2px rgba(16,44,85,.12);font:600 11px Inter,Arial,sans-serif;color:#102C55;white-space:nowrap;line-height:1.35;">
        ${escapeHtml(row.city)}${row.isHq ? " (HQ)" : ""}<br/>
        <span style="font-weight:500;color:#52514e;">${escapeHtml(row.status)} · ${row.camerasOnline}/${row.camerasTotal} cams</span>
      </span>
    </div>`
}

type CityStatusMapProps = {
  className?: string
  tall?: boolean
  rows?: CityControlRow[]
}

/** Every location at its real position (office pin from Locations & Sync, else the city centre). */
export function CityStatusMap({ className, tall, rows = [] }: CityStatusMapProps) {
  const navigate = useNavigate()
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<{ L: Leaflet; map: LeafletMap } | null>(null)
  const markersRef = useRef<LeafletMarker[]>([])
  const fittedFor = useRef("")
  const [ready, setReady] = useState(false)
  const [failed, setFailed] = useState(false)

  const { placed, unplaced } = useMemo(() => {
    const placed: { row: CityControlRow; pos: [number, number] }[] = []
    const unplaced: CityControlRow[] = []
    for (const row of rows) {
      const pos = mapPosition(row.locationCode || row.id, row.latitude, row.longitude)
      if (pos) placed.push({ row, pos })
      else unplaced.push(row)
    }
    return { placed, unplaced }
  }, [rows])

  // Create the map once.
  useEffect(() => {
    let cancelled = false
    loadLeaflet()
      .then((L) => {
        if (cancelled || !containerRef.current) return
        const map = L.map(containerRef.current, { zoomControl: true, scrollWheelZoom: false, attributionControl: true })
        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
          maxZoom: 18,
          attribution: "&copy; OpenStreetMap contributors",
        }).addTo(map)
        map.setView([33.9, 71.9], 7)
        mapRef.current = { L, map }
        setReady(true)
      })
      .catch(() => setFailed(true))
    return () => {
      cancelled = true
      mapRef.current?.map.remove()
      mapRef.current = null
      markersRef.current = []
      fittedFor.current = ""
    }
  }, [])

  // Redraw pins on every refresh; re-fit only when the set of locations changes.
  useEffect(() => {
    const current = mapRef.current
    if (!ready || !current) return
    const { L, map } = current
    markersRef.current.forEach((m) => m.remove())
    markersRef.current = placed.map(({ row, pos }) => {
      const marker = L.marker(pos, {
        icon: L.divIcon({ html: pinHtml(row), className: "", iconSize: [0, 0] }),
        title: `${row.city}: ${row.status}`,
        keyboard: true,
      }).addTo(map)
      marker.on("click", () => navigate(`${ROUTES.CITY_CONTROL_GRID}/${row.id}`))
      return marker
    })
    const key = placed.map(({ row, pos }) => `${row.id}:${pos.join(",")}`).sort().join("|")
    if (key && key !== fittedFor.current) {
      fittedFor.current = key
      if (placed.length === 1) {
        map.setView(placed[0].pos, 12)
      } else {
        const group = L.featureGroup(markersRef.current)
        map.fitBounds(group.getBounds().pad(0.25), { maxZoom: 12 })
      }
    }
    map.invalidateSize()
  }, [ready, placed, navigate])

  return (
    <div
      className={cn(
        "flex min-h-[300px] flex-col overflow-hidden rounded-[10px] border border-[#D9E6F5] bg-white shadow-[0_1px_2px_rgba(16,44,85,0.04)]",
        className
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#D9E6F5] px-4 py-3">
        <h2 className="text-[15px] font-semibold text-[#102C55]">City Status Map</h2>
        <div className="flex items-center gap-3 text-[12px] text-[#52514e]">
          {LEGEND.map((label) => (
            <span key={label} className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: STATUS_COLOR[label] }} aria-hidden />
              {label}
            </span>
          ))}
        </div>
      </div>

      <div className={cn("relative flex-1", tall ? "min-h-[420px]" : "min-h-[300px]")}>
        <div ref={containerRef} className="absolute inset-0 z-0" aria-label="City Status Map" />
        {failed && (
          <div className="absolute inset-0 flex items-center justify-center bg-white/80 p-4 text-center text-[13px] text-[#607DA5]">
            The map could not load (no internet access to the map tiles).
          </div>
        )}
        {ready && rows.length === 0 && (
          <div className="pointer-events-none absolute inset-x-0 top-3 z-[400] mx-auto w-max rounded bg-white/95 px-3 py-1.5 text-[12px] text-[#607DA5] shadow">
            No locations yet. Add cities on Locations &amp; Sync.
          </div>
        )}
      </div>

      {unplaced.length > 0 && (
        <p className="border-t border-[#D9E6F5] px-4 py-2 text-[12px] text-[#607DA5]">
          Not on the map yet (set their Map location on Locations &amp; Sync):{" "}
          {unplaced.map((r) => `${r.city} (${r.status})`).join(", ")}
        </p>
      )}
    </div>
  )
}

export default CityStatusMap
