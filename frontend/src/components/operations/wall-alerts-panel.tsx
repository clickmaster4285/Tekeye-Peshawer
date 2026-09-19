"use client"

import { useEffect, useMemo } from "react"
import { Link } from "react-router-dom"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertTriangle, Bell } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { fetchDetectionEventsPage } from "@/lib/cameras-api"
import { REALTIME_INVALIDATE_EVENT } from "@/lib/realtime-socket"
import { ROUTES } from "@/routes/config"
import { cn } from "@/lib/utils"

function isCritical(className: string): boolean {
  const cls = (className || "").toLowerCase()
  return (
    cls.includes("weapon") ||
    cls === "gun" ||
    cls === "fire" ||
    cls.includes("flame") ||
    cls === "crowd"
  )
}

function titleFor(className: string): string {
  const pretty = (className || "").trim().replace(/[_-]+/g, " ")
  if (!pretty) return "Security alert"
  return `${pretty.replace(/\b\w/g, (c) => c.toUpperCase())}`
}

/** Dark live-alerts feed for the custom wall. */
export function WallAlertsPanel({ className }: { className?: string }) {
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ["wall-live-alerts"],
    queryFn: () => fetchDetectionEventsPage({ is_alert: true, page: 1, page_size: 30 }),
    refetchInterval: 20_000,
    refetchOnWindowFocus: true,
  })

  useEffect(() => {
    const onRealtime = (e: Event) => {
      const domains = (e as CustomEvent<{ domains?: string[] }>).detail?.domains || []
      if (domains.some((d) => ["alerts", "detections", "cameras"].includes(d))) {
        void queryClient.invalidateQueries({ queryKey: ["wall-live-alerts"] })
      }
    }
    window.addEventListener(REALTIME_INVALIDATE_EVENT, onRealtime)
    return () => window.removeEventListener(REALTIME_INVALIDATE_EVENT, onRealtime)
  }, [queryClient])

  const events = data?.results || []
  const critical = useMemo(
    () => events.filter((e) => isCritical(String(e.class_name || ""))).length,
    [events],
  )

  return (
    <div className={cn("flex h-full min-h-0 flex-col bg-zinc-950", className)}>
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-white/10 px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <Bell className="h-3.5 w-3.5 shrink-0 text-amber-400" />
          <p className="truncate text-xs font-semibold uppercase tracking-wide text-white/80">
            Live alerts
          </p>
        </div>
        <div className="flex items-center gap-2">
          {critical > 0 ? (
            <Badge className="border-0 bg-red-500/20 text-[10px] font-medium text-red-300">
              {critical} critical
            </Badge>
          ) : null}
          <Link
            to={`${ROUTES.OBJECT_DETECTION}?alert=1`}
            className="text-[10px] font-medium text-sky-400 hover:text-sky-300"
          >
            View all
          </Link>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {isLoading && events.length === 0 ? (
          <p className="px-3 py-8 text-center text-xs text-white/40">Loading alerts…</p>
        ) : events.length === 0 ? (
          <p className="px-3 py-8 text-center text-xs text-white/40">No live alerts</p>
        ) : (
          <ul className="divide-y divide-white/5">
            {events.map((ev) => {
              const cls = String(ev.class_name || "")
              const crit = isCritical(cls)
              const when = ev.created_at
                ? new Date(ev.created_at).toLocaleTimeString()
                : ""
              return (
                <li key={ev.id}>
                  <Link
                    to={`${ROUTES.OBJECT_DETECTION}?alert=1&q=${encodeURIComponent(cls)}`}
                    className={cn(
                      "flex gap-2 px-3 py-2.5 transition-colors hover:bg-white/5",
                      crit && "bg-red-500/5",
                    )}
                  >
                    <AlertTriangle
                      className={cn(
                        "mt-0.5 h-3.5 w-3.5 shrink-0",
                        crit ? "text-red-400" : "text-amber-400",
                      )}
                    />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-semibold text-white">
                        {titleFor(cls)}
                      </p>
                      <p className="mt-0.5 truncate text-[10px] text-white/45">
                        {[ev.camera_name || ev.camera_code, when].filter(Boolean).join(" · ")}
                      </p>
                    </div>
                  </Link>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}
