import { useCallback, useEffect, useMemo, useState } from "react"
import { Calendar, RefreshCw } from "lucide-react"
import { ModulePageLayout } from "@/components/dashboard/module-page-layout"
import { DashboardOverviewPanel } from "@/components/dashboard/dashboard-overview-panel"
import { DashboardQuickActions } from "@/components/dashboard/dashboard-quick-actions"
import { DashboardNotifications } from "@/components/dashboard/dashboard-notifications"
import { DashboardAlertFeed } from "@/components/dashboard/dashboard-alert-feed"
import { DashboardStatisticsWidgets } from "@/components/dashboard/dashboard-statistics-widgets"
import { DashboardLiveCameraGrid } from "@/components/dashboard/dashboard-live-camera-grid"
import { CityStatusMap } from "@/components/city-control/CityStatusMap"
import { AiAnalyticsPanel } from "@/components/analytics/ai-analytics-panel"
import { EventLog } from "@/components/analytics/event-log"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { fetchCityControlGridLive, type CityControlRow } from "@/data/city-control-grid-data"
import { ALL_LOCATIONS, fetchAnalytics, type AnalyticsData } from "@/lib/analytics-api"

const REFRESH_MS = 30_000

function isoDay(d: Date): string {
  const local = new Date(d.getTime() - d.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 10)
}

function daysAgo(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return isoDay(d)
}

function rangeLabel(from: string, to: string): string {
  const fmt = (s: string) => new Date(`${s}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" })
  return from === to ? fmt(from) : `${fmt(from)} – ${fmt(to)}`
}

export default function AnalyticsDashboardPage() {
  const [location, setLocation] = useState(ALL_LOCATIONS)
  const [from, setFrom] = useState(() => daysAgo(6))
  const [to, setTo] = useState(() => isoDay(new Date()))
  const [data, setData] = useState<AnalyticsData | undefined>()
  const [mapRows, setMapRows] = useState<CityControlRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)

  const query = useMemo(() => ({ location, from, to }), [location, from, to])

  const load = useCallback(
    (signal?: AbortSignal) => {
      setLoading(true)
      return fetchAnalytics(query, signal)
        .then((res) => {
          setData(res)
          setError("")
          setLastRefresh(new Date())
        })
        .catch((err: unknown) => {
          if (!signal?.aborted) setError(err instanceof Error ? err.message : "Could not load the dashboard.")
        })
        .finally(() => {
          if (!signal?.aborted) setLoading(false)
        })
    },
    [query]
  )

  // Load on filter change, then refresh quietly every 30s while the tab is visible.
  useEffect(() => {
    const ac = new AbortController()
    void load(ac.signal)
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        void load(ac.signal)
        setRefreshKey((k) => k + 1)
      }
    }, REFRESH_MS)
    return () => {
      window.clearInterval(timer)
      ac.abort()
    }
  }, [load])

  useEffect(() => {
    const ac = new AbortController()
    fetchCityControlGridLive({ signal: ac.signal })
      .then((live) => setMapRows(live.rows))
      .catch(() => {})
    return () => ac.abort()
  }, [refreshKey])

  const label = rangeLabel(from, to)
  const scopeName =
    location === ALL_LOCATIONS ? "All locations" : data?.locations.find((l) => l.code === location)?.name || location
  const mapRowsInScope =
    location === ALL_LOCATIONS ? mapRows : mapRows.filter((r) => (r.locationCode || "").toUpperCase() === location)

  return (
    <ModulePageLayout
      title="Analytics Dashboard"
      description="Live overview of cameras, AI detections and alerts across Peshawar and every connected city."
      breadcrumbs={[{ label: "AI Analytics" }, { label: "Analytics Dashboard" }]}
    >
      <div className="mb-6 flex flex-col gap-4">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="grid gap-1">
              <Label className="text-xs text-muted-foreground">Location</Label>
              <Select value={location} onValueChange={setLocation}>
                <SelectTrigger className="h-9 w-48">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL_LOCATIONS}>All locations</SelectItem>
                  {(data?.locations ?? []).map((l) => (
                    <SelectItem key={l.code} value={l.code}>
                      {l.name}
                      {l.is_hq ? " (head office)" : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1">
              <Label className="text-xs text-muted-foreground">From</Label>
              <Input type="date" value={from} max={to} onChange={(e) => e.target.value && setFrom(e.target.value)} className="h-9 w-40" />
            </div>
            <div className="grid gap-1">
              <Label className="text-xs text-muted-foreground">To</Label>
              <Input
                type="date"
                value={to}
                min={from}
                max={isoDay(new Date())}
                onChange={(e) => e.target.value && setTo(e.target.value)}
                className="h-9 w-40"
              />
            </div>
            <div className="flex gap-1">
              {[
                { label: "Today", days: 0 },
                { label: "7 days", days: 6 },
                { label: "30 days", days: 29 },
              ].map((p) => (
                <Button
                  key={p.label}
                  variant="outline"
                  size="sm"
                  className="h-9"
                  onClick={() => {
                    setFrom(daysAgo(p.days))
                    setTo(isoDay(new Date()))
                  }}
                >
                  {p.label}
                </Button>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-2 text-sm text-muted-foreground">
              <Calendar className="h-4 w-4" />
              {lastRefresh ? `Updated ${lastRefresh.toLocaleTimeString("en-GB")}` : "Loading…"}
            </span>
            <Button
              variant="outline"
              size="icon"
              onClick={() => {
                void load()
                setRefreshKey((k) => k + 1)
              }}
              aria-label="Refresh now"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            </Button>
            <DashboardNotifications alerts={data?.alerts ?? []} incidents={data?.overview.incidents_today ?? 0} />
          </div>
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <DashboardQuickActions />
      </div>

      <div className="space-y-6">
        <DashboardOverviewPanel overview={data?.overview} />

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <DashboardLiveCameraGrid />
          <DashboardAlertFeed alerts={data?.alerts ?? []} loading={loading && !data} />
        </div>

        <DashboardStatisticsWidgets stats={data?.stats} rangeLabel={`${scopeName} · ${label}`} />

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Locations map</CardTitle>
          </CardHeader>
          <CardContent>
            <CityStatusMap rows={mapRowsInScope} />
          </CardContent>
        </Card>

        <AiAnalyticsPanel data={data} rangeLabel={`${scopeName} · ${label}`} />

        <EventLog query={query} refreshKey={refreshKey} />
      </div>
    </ModulePageLayout>
  )
}
