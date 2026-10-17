import { Car, Crosshair, IdCard, ScanFace, ShieldAlert, Users } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { AnalyticsData } from "@/lib/analytics-api"

const TILES: {
  key: keyof AnalyticsData["stats"]
  label: string
  icon: typeof Users
}[] = [
  { key: "people", label: "People detected", icon: Users },
  { key: "vehicles", label: "Vehicles detected", icon: Car },
  { key: "weapons", label: "Weapons detected", icon: Crosshair },
  { key: "plates", label: "Plates read", icon: IdCard },
  { key: "face_matches", label: "Face matches (attendance)", icon: ScanFace },
  { key: "blacklist_encounters", label: "Blacklist / security alerts", icon: ShieldAlert },
]

/** Totals for the selected location and date range. */
export function DashboardStatisticsWidgets({ stats, rangeLabel }: { stats?: AnalyticsData["stats"]; rangeLabel: string }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-base">Statistics</CardTitle>
        <span className="text-xs text-muted-foreground">
          {rangeLabel}
          {stats ? ` · ${stats.total.toLocaleString()} detections` : ""}
        </span>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
        {TILES.map(({ key, label, icon: Icon }) => (
          <div key={key} className="rounded-lg border border-border p-4">
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Icon className="h-4 w-4" />
              {label}
            </p>
            <p className="mt-1 text-2xl font-semibold tabular-nums text-foreground">
              {stats ? stats[key].toLocaleString() : "—"}
            </p>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}
