import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { SeverityBadge } from "@/components/analytics/palette"
import type { AnalyticsData, Severity } from "@/lib/analytics-api"

const SEVERITIES: { label: Severity; key: keyof AnalyticsData["overview"]["alerts_by_severity"] }[] = [
  { label: "Critical", key: "critical" },
  { label: "High", key: "high" },
  { label: "Medium", key: "medium" },
  { label: "Low", key: "low" },
]

function Tile({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <div className="mt-0.5">{children}</div>
    </div>
  )
}

/** Today's alerts and the live state of cameras, AI, locations and storage for the selected scope. */
export function DashboardOverviewPanel({ overview }: { overview?: AnalyticsData["overview"] }) {
  const o = overview
  const health = o?.system_health
  const healthColor =
    health == null ? "text-foreground" : health >= 90 ? "text-green-600" : health >= 70 ? "text-amber-600" : "text-red-600"

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Overview</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <p className="mb-1.5 text-xs text-muted-foreground">Alerts today by severity</p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {SEVERITIES.map(({ label, key }) => (
              <div key={key} className="rounded-md border border-border p-2">
                <SeverityBadge severity={label} />
                <p className="mt-1 text-xl font-semibold tabular-nums text-foreground">
                  {o ? o.alerts_by_severity[key].toLocaleString() : "—"}
                </p>
              </div>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-7">
          <Tile label="Cameras online">
            <p className="text-xl font-semibold tabular-nums text-foreground">
              {o ? `${o.cameras_online} / ${o.cameras_total}` : "—"}
            </p>
          </Tile>
          <Tile label="Cameras offline">
            <p className={`text-xl font-semibold tabular-nums ${o && o.cameras_offline > 0 ? "text-red-600" : "text-foreground"}`}>
              {o ? o.cameras_offline : "—"}
            </p>
          </Tile>
          <Tile label="Incidents today">
            <p className="text-xl font-semibold tabular-nums text-foreground">{o ? o.incidents_today.toLocaleString() : "—"}</p>
          </Tile>
          <Tile label="Locations online">
            <p className="text-xl font-semibold tabular-nums text-foreground">
              {o ? `${o.locations_online} / ${o.locations_total}` : "—"}
            </p>
          </Tile>
          <Tile label="System health">
            <p className={`text-xl font-semibold tabular-nums ${healthColor}`}>{health == null ? "—" : `${health}%`}</p>
          </Tile>
          <Tile label="AI processing">
            <p className={`text-sm font-semibold ${o?.ai_processing === "online" ? "text-green-600" : "text-red-600"}`}>
              {o ? (o.ai_processing === "online" ? "● Online" : "● Offline") : "—"}
            </p>
          </Tile>
          <Tile label="Storage usage">
            {o?.storage_percent == null ? (
              <p className="text-sm text-muted-foreground">Not reported</p>
            ) : (
              <>
                <Progress value={o.storage_percent} className="mt-2 h-2" />
                <p className="mt-1 text-xs text-muted-foreground">{o.storage_percent}% used</p>
              </>
            )}
          </Tile>
        </div>
      </CardContent>
    </Card>
  )
}
