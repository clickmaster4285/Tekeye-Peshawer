import { useEffect, useMemo, useRef, useState } from "react"
import { fetchDetectionEventsPage } from "@/lib/cameras-api"

export type CameraAlertBadge = {
  count: number
  label: string
  at: string
}

type Options = {
  /** How often to refresh. Kept well above the video frame rate on purpose. */
  intervalMs?: number
  /** Only count alerts raised within this window. */
  windowSec?: number
  enabled?: boolean
}

/**
 * One poll of the detection-events feed for a whole camera grid, bucketed per
 * camera. This is the alert channel for the live wall: the tiles play a plain
 * view stream and show a badge, so no tile ever requests detection frames.
 */
export function useCameraAlertBadges(
  cameraIds: number[],
  { intervalMs = 5000, windowSec = 120, enabled = true }: Options = {}
): Record<number, CameraAlertBadge> {
  const [badges, setBadges] = useState<Record<number, CameraAlertBadge>>({})
  const idKey = useMemo(() => [...cameraIds].sort((a, b) => a - b).join(","), [cameraIds])
  const idSetRef = useRef<Set<number>>(new Set())
  idSetRef.current = new Set(cameraIds)

  useEffect(() => {
    if (!enabled || !idKey) {
      setBadges({})
      return
    }
    let cancelled = false

    const run = async () => {
      if (document.visibilityState !== "visible") return
      const since = new Date(Date.now() - Math.max(10, windowSec) * 1000).toISOString()
      try {
        const page = await fetchDetectionEventsPage({
          page: 1,
          page_size: 100,
          is_alert: true,
          date_from: since,
        })
        if (cancelled) return
        const next: Record<number, CameraAlertBadge> = {}
        for (const event of page.results || []) {
          if (!idSetRef.current.has(event.camera)) continue
          const current = next[event.camera]
          next[event.camera] = {
            count: (current?.count || 0) + 1,
            label: current?.label || event.label || event.class_name || "Alert",
            at: current?.at || event.created_at,
          }
        }
        setBadges(next)
      } catch {
        // Badges are advisory — a failed poll must never disturb playback.
      }
    }

    void run()
    const timer = window.setInterval(run, Math.max(2000, intervalMs))
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [idKey, intervalMs, windowSec, enabled])

  return badges
}
