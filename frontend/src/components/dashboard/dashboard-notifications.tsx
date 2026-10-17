import { Bell } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { SeverityBadge } from "@/components/analytics/palette"
import type { AnalyticsDetection } from "@/lib/analytics-api"

/** Bell with today's critical + high alerts count and the latest few alerts. */
export function DashboardNotifications({ alerts, incidents }: { alerts: AnalyticsDetection[]; incidents: number }) {
  const latest = alerts.slice(0, 6)
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="icon" className="relative" aria-label={`${incidents} alerts today`}>
          <Bell className="h-4 w-4" />
          {incidents > 0 && (
            <span className="absolute -right-1.5 -top-1.5 min-w-[18px] rounded-full bg-destructive px-1 text-[10px] font-bold leading-[18px] text-destructive-foreground">
              {incidents > 99 ? "99+" : incidents}
            </span>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel>Latest alerts</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {latest.length === 0 ? (
          <DropdownMenuItem disabled>No alerts in the last 24 hours</DropdownMenuItem>
        ) : (
          latest.map((a) => (
            <DropdownMenuItem key={a.id} className="flex items-center justify-between gap-2">
              <span className="min-w-0 truncate text-xs">
                {a.object || a.type} · {a.camera} · {a.location}
              </span>
              <SeverityBadge severity={a.severity} />
            </DropdownMenuItem>
          ))
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
