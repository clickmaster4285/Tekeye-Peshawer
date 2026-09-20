import { memo, useCallback, useEffect, useRef, useState } from "react"
import { Maximize2, Minimize2 } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  fetchMlLiveDetections,
  getMlLiveMultipartUrl,
  getViewMjpegUrl,
  cameraSourceLabel,
  type CameraRecord,
} from "@/lib/cameras-api"
import { cn } from "@/lib/utils"
import { CUSTOMS_LOGO_SRC } from "@/lib/brand"

type DetectionBox = {
  class_name?: string
  label: string
  confidence: number
  bbox: [number, number, number, number]
  alert?: boolean
}

type MlCameraFeedProps = {
  camera: CameraRecord
  /** Extra detection JSON polling — off by default; used only to feed alert badges/logs. */
  pollMl?: boolean
  pollIntervalMs?: number
  className?: string
  showBrandLogo?: boolean
  showFullscreenButton?: boolean
  /** Recent alert count for this camera — shown as a badge, never as boxes. */
  alertCount?: number
  alertLabel?: string
  onDetections?: (boxes: DetectionBox[]) => void
  onMlError?: (message: string) => void
  onScanStart?: () => void
}

const TEKEYE_LOGO_SRC = CUSTOMS_LOGO_SRC

function StreamBrandMarks() {
  return (
    <>
      <div
        className="absolute top-3 left-3 z-10 rounded-lg border border-white/10 bg-black/50 px-3 py-2 pointer-events-none backdrop-blur-sm"
        aria-hidden
      >
        <img
          src={TEKEYE_LOGO_SRC}
          alt="Pakistan Customs"
          className="h-12 w-auto max-w-[180px] object-contain sm:h-14"
        />
      </div>
      <div
        className="absolute bottom-3 right-3 z-10 rounded-lg border border-white/10 bg-black/50 px-4 py-2.5 pointer-events-none backdrop-blur-sm"
        aria-hidden
      >
        <span className="text-xl font-extrabold uppercase tracking-[0.16em] text-white sm:text-2xl">
          CIIS
        </span>
      </div>
    </>
  )
}

function MlCameraFeedImpl({
  camera,
  pollMl = false,
  pollIntervalMs = 5000,
  className = "",
  showBrandLogo = true,
  showFullscreenButton = false,
  alertCount = 0,
  alertLabel,
  onDetections,
  onMlError,
  onScanStart,
}: MlCameraFeedProps) {
  const [mlError, setMlError] = useState<string | null>(null)
  const [streamError, setStreamError] = useState<string | null>(null)
  const [streamRetry, setStreamRetry] = useState(0)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [pageVisible, setPageVisible] = useState(
    () => typeof document === "undefined" || document.visibilityState === "visible"
  )
  const retryTimer = useRef<number | null>(null)

  useEffect(() => {
    const onVis = () => setPageVisible(document.visibilityState === "visible")
    document.addEventListener("visibilitychange", onVis)
    return () => document.removeEventListener("visibilitychange", onVis)
  }, [])

  const annotatedSrc = getMlLiveMultipartUrl(camera)
  const viewSrc = getViewMjpegUrl(camera)
  // Live panels never draw detection tags/boxes — always play the box-free raw stream.
  // Detections still run server-side and surface as log entries (ObjectDetection page)
  // and alert badges, not as overlays on the video.
  const streamSrcBase = viewSrc || annotatedSrc
  const streamSrc = streamSrcBase && pageVisible
    ? `${streamSrcBase}${streamSrcBase.includes("?") ? "&" : "?"}r=${streamRetry}`
    : null

  const exitFullscreen = useCallback(() => setIsFullscreen(false), [])

  // Callers commonly pass inline closures. Keeping them in refs stops the poll effect
  // from tearing down on every parent render (which re-fired the request immediately
  // and turned pollIntervalMs into a tight request loop).
  const cbRef = useRef({ onDetections, onMlError, onScanStart })
  useEffect(() => {
    cbRef.current = { onDetections, onMlError, onScanStart }
  }, [onDetections, onMlError, onScanStart])

  useEffect(() => {
    return () => {
      if (retryTimer.current != null) window.clearTimeout(retryTimer.current)
    }
  }, [])

  useEffect(() => {
    // Detection JSON is optional — the annotated MJPEG already includes overlays.
    if (!pollMl || !annotatedSrc || !pageVisible) return
    let cancelled = false

    const run = async () => {
      cbRef.current.onScanStart?.()
      try {
        const result = await fetchMlLiveDetections(camera.id)
        if (cancelled) return
        const next = (result.detections || []).map((d) => ({
          class_name: d.class_name,
          label: d.label,
          confidence: d.confidence,
          bbox: d.bbox,
          alert: d.alert,
        }))
        setMlError(null)
        cbRef.current.onDetections?.(next)
      } catch (err) {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : "ML detection failed"
          setMlError(msg)
          cbRef.current.onMlError?.(msg)
        }
      }
    }

    void run()
    const id = window.setInterval(run, Math.max(2000, pollIntervalMs))
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [camera.id, annotatedSrc, pollMl, pollIntervalMs, pageVisible])

  useEffect(() => {
    if (!isFullscreen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") exitFullscreen()
    }
    document.addEventListener("keydown", onKey)
    document.body.style.overflow = "hidden"
    return () => {
      document.removeEventListener("keydown", onKey)
      document.body.style.overflow = ""
    }
  }, [isFullscreen, exitFullscreen])

  return (
    <div
      className={cn(
        "flex flex-col",
        isFullscreen &&
        "fixed inset-0 z-[250] flex h-[100dvh] max-h-[100dvh] w-full flex-col bg-black",
        className
      )}
    >
      <div
        className={cn(
          "relative aspect-video w-full overflow-hidden bg-black",
          isFullscreen && "min-h-0 flex-1 aspect-auto"
        )}
      >
        {streamSrc ? (
          <img
            key={`${streamSrcBase}-${streamRetry}`}
            src={streamSrc}
            alt={camera.name}
            decoding="async"
            className="h-full w-full object-contain"
            onLoad={() => setStreamError(null)}
            onError={() => {
              if (retryTimer.current != null) window.clearTimeout(retryTimer.current)
              if (streamRetry < 12) {
                retryTimer.current = window.setTimeout(() => {
                  setStreamRetry((n) => n + 1)
                }, 4000)
                return
              }
              setStreamError("Stream failed — ensure the ML service is running.")
            }}
          />
        ) : (
          <div className="flex h-full min-h-[120px] items-center justify-center px-4 text-center text-sm text-muted-foreground">
            Configure an NVR channel for this camera in Camera Management.
          </div>
        )}

        <div className="absolute top-2 left-2 z-10 flex max-w-[70%] flex-wrap gap-1">
          <Badge variant="secondary" className="text-xs">
            {camera.name}
          </Badge>
          {streamSrcBase && <Badge className="bg-[#3b82f6] text-xs">Live</Badge>}
          {alertCount > 0 && (
            <Badge className="bg-red-600 text-xs text-white" title={alertLabel}>
              {alertLabel ? `${alertLabel} · ${alertCount}` : `${alertCount} alert${alertCount > 1 ? "s" : ""}`}
            </Badge>
          )}
        </div>

        {showFullscreenButton && (
          <Button
            type="button"
            size="icon"
            variant="ghost"
            className="absolute top-2 right-2 z-20 h-8 w-8 bg-black/55 text-white hover:bg-black/75 hover:text-white"
            onClick={() => (isFullscreen ? exitFullscreen() : setIsFullscreen(true))}
            title={isFullscreen ? "Exit full screen (Esc)" : "View full screen"}
            aria-label={isFullscreen ? "Exit full screen" : "View full screen"}
          >
            {isFullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
          </Button>
        )}

        {showBrandLogo && <StreamBrandMarks />}

        {(streamError || mlError) && (
          <p className="absolute bottom-10 left-1 right-1 z-10 truncate rounded bg-black/60 px-1 text-[10px] text-amber-300">
            {streamError || mlError}
          </p>
        )}
      </div>

      {isFullscreen && (
        <div className="shrink-0 border-t border-white/10 bg-black/90 px-4 py-2 text-center text-xs text-white/80">
          {camera.name}
          {" · "}
          {cameraSourceLabel(camera)}
          {" · "}
          Press Esc or tap minimize to exit
        </div>
      )}
    </div>
  )
}

// Memoized: on grid pages this re-renders on every 5s alert-badge poll otherwise,
// since a new alertCount/onDetections closure gets passed down each tick.
export const MlCameraFeed = memo(MlCameraFeedImpl)
