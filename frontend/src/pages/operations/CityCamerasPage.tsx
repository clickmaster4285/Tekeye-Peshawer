import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { AlertTriangle, ArrowLeft, Camera, Loader2, VideoOff } from "lucide-react"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { cityCameraStreamUrl, fetchCityCameras, type CityCamerasView } from "@/lib/ops-central-api"
import { ROUTES } from "@/routes/config"
import { cn } from "@/lib/utils"

/** Grid frames refresh this often; a full live stream opens only for the camera you click. */
const FRAME_REFRESH_MS = 3000

type CityCamera = CityCamerasView["cameras"][number]

function codeFromCityId(cityId: string): string {
  return cityId.toUpperCase().replace(/-/g, "_")
}

function CameraTile({
  view,
  camera,
  tick,
  onOpen,
}: {
  view: CityCamerasView
  camera: CityCamera
  tick: number
  onOpen: () => void
}) {
  const [failed, setFailed] = useState(false)
  const [loaded, setLoaded] = useState(false)

  // A new frame (or a renewed pass) gives the camera another chance after a failure.
  useEffect(() => setFailed(false), [tick, view.pass])

  return (
    <button
      type="button"
      onClick={onOpen}
      className="group overflow-hidden rounded-[10px] border border-[#D9E6F5] bg-white text-left shadow-[0_1px_2px_rgba(16,44,85,0.04)] transition-shadow hover:shadow-md"
    >
      <div className="relative aspect-video bg-[#0B1B33]">
        {failed ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 text-[12px] text-[#A9BBD3]">
            <VideoOff className="h-5 w-5" />
            No video
          </div>
        ) : (
          <>
            {!loaded && (
              <div className="absolute inset-0 flex items-center justify-center text-[#A9BBD3]">
                <Loader2 className="h-5 w-5 animate-spin" />
              </div>
            )}
            <img
              src={cityCameraStreamUrl(view, camera.id, "jpeg", tick)}
              alt={camera.name}
              className="absolute inset-0 h-full w-full object-cover"
              onLoad={() => setLoaded(true)}
              onError={() => setFailed(true)}
            />
          </>
        )}
      </div>
      <div className="px-3 py-2">
        <p className="truncate text-[13px] font-semibold text-[#102C55]">{camera.name}</p>
        <p className="truncate text-[11px] text-[#607DA5]">
          {[camera.zone, camera.location, camera.site_name].filter(Boolean).join(" · ") || `Camera ${camera.id}`}
        </p>
      </div>
    </button>
  )
}

export default function CityCamerasPage() {
  const { cityId = "" } = useParams()
  const code = codeFromCityId(cityId)
  const [view, setView] = useState<CityCamerasView | null>(null)
  const [error, setError] = useState("")
  const [tick, setTick] = useState(() => Date.now())
  // The live URL is fixed when opened, so renewing the pass does not restart the stream.
  const [open, setOpen] = useState<{ camera: CityCamera; url: string } | null>(null)

  // Camera list + view pass; renewed a minute before the pass expires.
  useEffect(() => {
    const ac = new AbortController()
    let timer = 0
    const load = () =>
      fetchCityCameras(code, { signal: ac.signal })
        .then((data) => {
          setView(data)
          setError("")
          timer = window.setTimeout(load, Math.max(60, data.pass_ttl_sec - 60) * 1000)
        })
        .catch((err: unknown) => {
          if (ac.signal.aborted) return
          setError(err instanceof Error ? err.message : "Could not load cameras.")
          timer = window.setTimeout(load, 30_000)
        })
    void load()
    return () => {
      window.clearTimeout(timer)
      ac.abort()
    }
  }, [code])

  // Fresh grid frames while the tab is visible.
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") setTick(Date.now())
    }, FRAME_REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [])

  const blockedByHttps =
    typeof window !== "undefined" && window.location.protocol === "https:" && view?.base_url.startsWith("http:")
  const offline = view && view.state !== "ONLINE" && view.state !== "DEGRADED"

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link
            to={`${ROUTES.CITY_CONTROL_GRID}/${cityId}`}
            className="inline-flex items-center gap-1 text-[12px] font-semibold text-[#0875E1] hover:underline"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> Back to {view?.name || "city"}
          </Link>
          <h1 className="mt-1 inline-flex items-center gap-2 text-[20px] font-bold text-[#102C55]">
            <Camera className="h-5 w-5 text-[#607DA5]" />
            {view?.name || code} cameras
          </h1>
          {view && (
            <p className="text-[12px] text-[#607DA5]">
              Video comes directly from {view.base_url}. Nothing streams through Peshawar.
            </p>
          )}
        </div>
        {view && (
          <span
            className={cn(
              "rounded border px-2 py-1 text-[11px] font-bold uppercase tracking-wide",
              offline ? "border-[#F7C9CD] bg-[#FFECEE] text-[#FF4D59]" : "border-[#BFE8D4] bg-[#E8F8F1] text-[#12A66A]"
            )}
          >
            {offline ? "City offline" : `${view.cameras.length} cameras`}
          </span>
        )}
      </div>

      {(error || blockedByHttps || offline) && (
        <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            {error ||
              (blockedByHttps
                ? "This page is open over https but the city server uses http, so the browser blocks its video. Open Peshawar over http, or give the city https."
                : "The city has not sent a heartbeat recently. Its cameras may not answer.")}
          </span>
        </div>
      )}

      {!view && !error ? (
        <div className="flex items-center justify-center rounded-[10px] border border-[#D9E6F5] bg-white py-16 text-[#607DA5]">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading cameras…
        </div>
      ) : view && view.cameras.length === 0 ? (
        <div className="rounded-[10px] border border-[#D9E6F5] bg-white py-16 text-center text-[13px] text-[#607DA5]">
          This city has not sent its camera list yet. It arrives with the next heartbeat.
        </div>
      ) : view ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
          {view.cameras.map((camera) => (
            <CameraTile key={camera.id} view={view} camera={camera} tick={tick} onOpen={() => setOpen({ camera, url: cityCameraStreamUrl(view, camera.id, "live") })} />
          ))}
        </div>
      ) : null}

      <Dialog open={Boolean(open)} onOpenChange={(o) => !o && setOpen(null)}>
        <DialogContent className="max-w-5xl">
          <DialogHeader>
            <DialogTitle>
              {view?.name} – {open?.camera.name}
            </DialogTitle>
          </DialogHeader>
          {open && (
            <div className="relative aspect-video overflow-hidden rounded-md bg-black">
              {/* Live MJPEG straight from the city; the pass is only checked when the stream starts. */}
              <img
                src={open.url}
                alt={open.camera.name}
                className="h-full w-full object-contain"
              />
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
