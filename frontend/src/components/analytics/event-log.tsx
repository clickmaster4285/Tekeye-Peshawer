import { useEffect, useState } from "react"
import { ChevronLeft, ChevronRight, Loader2, Search } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { DetectionThumb } from "@/components/city-control/detection-thumb"
import {
  fetchEventLog,
  type AnalyticsQuery,
  type DetectionKind,
  type EventLogPage,
  type Severity,
} from "@/lib/analytics-api"
import { SeverityBadge } from "./palette"

const SEVERITIES: Severity[] = ["Critical", "High", "Medium", "Low"]
const TYPES: DetectionKind[] = ["Person", "Vehicle", "Weapon", "License Plate", "Other"]

function toggle<T>(list: T[], item: T): T[] {
  return list.includes(item) ? list.filter((x) => x !== item) : [...list, item]
}

/** Searchable detection log for the selected location and range. */
export function EventLog({ query, refreshKey }: { query: AnalyticsQuery; refreshKey: number }) {
  const [search, setSearch] = useState("")
  const [q, setQ] = useState("")
  const [severities, setSeverities] = useState<Severity[]>([])
  const [types, setTypes] = useState<DetectionKind[]>([])
  const [page, setPage] = useState(1)
  const [data, setData] = useState<EventLogPage | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  // Search waits until typing stops.
  useEffect(() => {
    const t = window.setTimeout(() => setQ(search), 400)
    return () => window.clearTimeout(t)
  }, [search])

  useEffect(() => setPage(1), [q, severities, types, query.location, query.from, query.to])

  useEffect(() => {
    const ac = new AbortController()
    setLoading(true)
    fetchEventLog({ ...query, q, severities, types, page }, ac.signal)
      .then((res) => {
        setData(res)
        setError("")
      })
      .catch((err: unknown) => {
        if (!ac.signal.aborted) setError(err instanceof Error ? err.message : "Could not load events.")
      })
      .finally(() => {
        if (!ac.signal.aborted) setLoading(false)
      })
    return () => ac.abort()
  }, [query, q, severities, types, page, refreshKey])

  const pages = data ? Math.max(1, Math.ceil(data.count / data.page_size)) : 1

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          Event log
          {loading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-2 h-4 w-4 text-muted-foreground" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search object, camera, name"
              className="h-8 w-60 pl-8"
            />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {SEVERITIES.map((s) => (
              <label key={s} className="flex items-center gap-1.5 text-xs">
                <Checkbox checked={severities.includes(s)} onCheckedChange={() => setSeverities((v) => toggle(v, s))} />
                {s}
              </label>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {TYPES.map((t) => (
              <label key={t} className="flex items-center gap-1.5 text-xs">
                <Checkbox checked={types.includes(t)} onCheckedChange={() => setTypes((v) => toggle(v, t))} />
                {t}
              </label>
            ))}
          </div>
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <div className="overflow-x-auto rounded border border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/30 text-left text-xs text-muted-foreground">
                <th className="p-2 font-medium">Image</th>
                <th className="p-2 font-medium">Time</th>
                <th className="p-2 font-medium">Type</th>
                <th className="p-2 font-medium">Object</th>
                <th className="p-2 font-medium">Camera</th>
                <th className="p-2 font-medium">Location</th>
                <th className="p-2 text-right font-medium">Confidence</th>
                <th className="p-2 font-medium">Severity</th>
              </tr>
            </thead>
            <tbody>
              {!data?.results.length ? (
                <tr>
                  <td colSpan={8} className="p-6 text-center text-muted-foreground">
                    {loading ? "Loading…" : "No events match."}
                  </td>
                </tr>
              ) : (
                data.results.map((e) => (
                  <tr key={e.id} className="border-b border-border last:border-0">
                    <td className="p-1.5">
                      <DetectionThumb src={e.image} alt={e.object} size={36} />
                    </td>
                    <td className="whitespace-nowrap p-2 tabular-nums text-muted-foreground">{e.time}</td>
                    <td className="p-2">{e.type}</td>
                    <td className="p-2">{e.object}</td>
                    <td className="p-2">{e.camera}</td>
                    <td className="p-2">{e.location}</td>
                    <td className="p-2 text-right tabular-nums">{e.confidence}%</td>
                    <td className="p-2">
                      <SeverityBadge severity={e.severity} />
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>{data ? `${data.count.toLocaleString()} events` : ""}</span>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} aria-label="Previous page">
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="tabular-nums">
              Page {page} / {pages}
            </span>
            <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => setPage((p) => p + 1)} aria-label="Next page">
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
