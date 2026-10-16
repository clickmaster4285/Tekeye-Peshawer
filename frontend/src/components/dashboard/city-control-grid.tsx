import { useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Eye } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import {
  CITY_CONTROL_REFRESH_MS,
  fetchCityControlGridLive,
  type CityControlAlert,
  type CityControlRow,
  type CityStatus,
} from "@/data/city-control-grid-data"
import { ROUTES } from "@/routes/config"

const STATUS_TEXT: Record<CityStatus, string> = {
  Online: "text-green-500",
  Degraded: "text-yellow-500",
  Offline: "text-red-500",
}

const STATUS_DOT: Record<CityStatus, string> = {
  Online: "bg-green-500",
  Degraded: "bg-yellow-500",
  Offline: "bg-red-500",
}

const getAlertBgColor = (alerts: number) => {
  if (alerts >= 5) return "bg-red-500"
  if (alerts >= 3) return "bg-orange-500"
  if (alerts >= 1) return "bg-yellow-500"
  return "bg-gray-300"
}

/** Dashboard summary of every city: live status, cameras, detections, seizures, detentions, alerts. */
export function CityControlGrid() {
  const navigate = useNavigate()
  const [rows, setRows] = useState<CityControlRow[]>([])
  const [alerts, setAlerts] = useState<CityControlAlert[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const ac = new AbortController()
    const load = (force: boolean) =>
      fetchCityControlGridLive({ signal: ac.signal, force })
        .then((live) => {
          if (ac.signal.aborted) return
          setRows(live.rows)
          setAlerts(live.alerts)
        })
        .catch(() => {
          // Keep the last good data on a failed refresh.
        })
        .finally(() => {
          if (!ac.signal.aborted) setLoading(false)
        })
    void load(false)
    const timer = window.setInterval(() => void load(true), CITY_CONTROL_REFRESH_MS)
    return () => {
      window.clearInterval(timer)
      ac.abort()
    }
  }, [])

  const alertsByCity = useMemo(() => {
    const counts = new Map<string, number>()
    for (const a of alerts) counts.set(a.city, (counts.get(a.city) ?? 0) + 1)
    return counts
  }, [alerts])

  const open = (row: CityControlRow) => navigate(`${ROUTES.CITY_CONTROL_GRID}/${row.id}`)

  return (
    <Card className="min-w-0 overflow-hidden rounded-[10px] border-gray-200 bg-white">
      <CardContent className="p-0">
        <div className="px-4 py-5 sm:px-6 sm:py-6">
          <h2 className="text-xl font-bold text-black sm:text-2xl">City Control Grid</h2>
          <p className="mt-1 text-sm text-gray-600">Real-time status of all connected cities</p>
        </div>
        <div className="border-t border-gray-200">
          <div className="overflow-x-auto min-h-[360px]">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 bg-gray-50">
                  <th className="px-4 py-3 text-left font-semibold text-black sm:px-6">CITY</th>
                  <th className="px-4 py-3 text-left font-semibold text-black sm:px-6">STATUS</th>
                  <th className="px-4 py-3 text-right font-semibold text-black sm:px-6">CAMERAS</th>
                  <th className="px-4 py-3 text-right font-semibold text-black sm:px-6">AI DETECTIONS (24H)</th>
                  <th className="px-4 py-3 text-right font-semibold text-black sm:px-6">SEIZURES (30D)</th>
                  <th className="px-4 py-3 text-right font-semibold text-black sm:px-6">DETENTIONS (30D)</th>
                  <th className="px-4 py-3 text-center font-semibold text-black sm:px-6">ALERTS</th>
                  <th className="px-4 py-3 text-center font-semibold text-black sm:px-6">ACTIONS</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {rows.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-10 text-center text-gray-500 sm:px-6">
                      {loading ? "Loading cities…" : "No cities connected yet."}
                    </td>
                  </tr>
                ) : (
                  rows.map((row) => {
                    const cityAlerts = alertsByCity.get(row.city) ?? 0
                    return (
                      <tr
                        key={row.id}
                        className="cursor-pointer border-0 transition-colors hover:bg-gray-50"
                        onClick={() => open(row)}
                      >
                        <td className="px-4 py-3 font-medium text-black sm:px-6">
                          {row.city}
                          {row.isHq && <span className="ml-1 text-xs text-gray-500">(Head Office)</span>}
                          <div className="text-xs font-normal text-gray-500">Last sync {row.lastSyncRelative}</div>
                        </td>
                        <td className="px-4 py-3 sm:px-6">
                          <span className={`inline-flex items-center gap-2 ${STATUS_TEXT[row.status]}`}>
                            <span className={`h-2 w-2 rounded-full ${STATUS_DOT[row.status]}`} />
                            {row.status}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-black sm:px-6">
                          {row.camerasOnline} / {row.camerasTotal}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-black sm:px-6">
                          {row.aiDetections24h.toLocaleString()}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-black sm:px-6">
                          {row.seizures30d.toLocaleString()}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-black sm:px-6">
                          {row.detentions30d.toLocaleString()}
                        </td>
                        <td className="px-4 py-3 text-center sm:px-6">
                          <span
                            className={`inline-flex h-6 min-w-6 items-center justify-center rounded-full px-1.5 text-xs font-bold text-white ${getAlertBgColor(cityAlerts)}`}
                          >
                            {cityAlerts}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-center sm:px-6">
                          <button
                            className="text-blue-500 transition-colors hover:text-blue-600"
                            onClick={(e) => {
                              e.stopPropagation()
                              open(row)
                            }}
                            type="button"
                            aria-label={`Open ${row.city}`}
                          >
                            <Eye className="h-5 w-5" />
                          </button>
                        </td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
