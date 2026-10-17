import { Link } from "react-router-dom"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { DetectionThumb } from "@/components/city-control/detection-thumb"
import { SeverityBadge } from "@/components/analytics/palette"
import type { AnalyticsDetection } from "@/lib/analytics-api"
import { ROUTES } from "@/routes/config"

function timeOf(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })
}

/** Weapon and AI alerts from the last 24 hours, newest first, with the detection picture. */
export function DashboardAlertFeed({ alerts, loading }: { alerts: AnalyticsDetection[]; loading: boolean }) {
  return (
    <Card className="flex flex-col">
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-base">Alert feed (last 24h)</CardTitle>
        <Link to={ROUTES.CITY_CONTROL_GRID} className="text-xs font-semibold text-primary hover:underline">
          All cities
        </Link>
      </CardHeader>
      <CardContent className="flex-1">
        {alerts.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">
            {loading ? "Loading alerts…" : "No alerts in the last 24 hours."}
          </p>
        ) : (
          <ul className="max-h-[420px] divide-y divide-border overflow-y-auto">
            {alerts.map((a) => (
              <li key={a.id} className="flex items-center gap-3 py-2">
                <DetectionThumb src={a.image} alt={a.object} size={44} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-foreground">
                    {a.object || a.type} · {a.camera}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {a.location} · {timeOf(a.at)}
                  </p>
                </div>
                <SeverityBadge severity={a.severity} />
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
