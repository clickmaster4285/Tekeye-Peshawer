"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Link, Navigate } from "react-router-dom"
import {
  Camera,
  Expand,
  Loader2,
  Maximize2,
  Minimize2,
  RefreshCw,
  Server,
  Trash2,
  Video,
  Wifi,
  WifiOff,
} from "lucide-react"
import { ModulePageLayout } from "@/components/dashboard/module-page-layout"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { getStoredUser } from "@/lib/auth"
import { normalizeRole } from "@/lib/role-access"
import { ROUTES } from "@/routes/config"
import {
  deleteRemoteServer,
  fetchAllCitiesStreams,
  removeServerCamera,
  withOpsStreamToken,
  type OpsCamera,
} from "@/lib/ops-central-api"
import { cn } from "@/lib/utils"

type CityCamera = OpsCamera & {
  server_id?: number
  server_name?: string
  location_code?: string
}

type ServerSummary = {
  id: number
  name: string
  location_code: string
  connection_mode: string
  ml_base_url: string
  last_health: string
  last_error: string
  ok: boolean
  source: string
  error: string
  camera_count: number
}

type GridLayout = "auto" | "1" | "2" | "3" | "4"

const GRID_CLASS: Record<GridLayout, string> = {
  auto: "grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4",
  "1": "grid-cols-1",
  "2": "grid-cols-1 sm:grid-cols-2",
  "3": "grid-cols-1 sm:grid-cols-2 xl:grid-cols-3",
  "4": "grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4",
}

function StreamTile({
  camera,
  showTimestamp,
  canManage,
  onRemove,
  removing,
}: {
  camera: CityCamera
  showTimestamp: boolean
  canManage?: boolean
  onRemove?: () => void
  removing?: boolean
}) {
  const [retry, setRetry] = useState(0)
  const [error, setError] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [now, setNow] = useState(() => new Date())
  const imgRef = useRef<HTMLImageElement | null>(null)
  const raw = (camera.ml_live_stream_url || "").trim()
  const tokenized = raw ? withOpsStreamToken(raw) : null
  const src = tokenized
    ? `${tokenized}${tokenized.includes("?") ? "&" : "?"}r=${retry}`
    : null

  const exitFullscreen = useCallback(() => setIsFullscreen(false), [])

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

  useEffect(() => {
    if (!showTimestamp && !isFullscreen) return
    const id = window.setInterval(() => setNow(new Date()), 1000)
    return () => window.clearInterval(id)
  }, [showTimestamp, isFullscreen])

  const refreshStream = () => {
    setError(false)
    setRetry((n) => n + 1)
  }

  const takeSnapshot = () => {
    const img = imgRef.current
    if (!img || !img.naturalWidth) return
    try {
      const canvas = document.createElement("canvas")
      canvas.width = img.naturalWidth
      canvas.height = img.naturalHeight
      const ctx = canvas.getContext("2d")
      if (!ctx) return
      ctx.drawImage(img, 0, 0)
      const link = document.createElement("a")
      const stamp = new Date().toISOString().replace(/[:.]/g, "-")
      link.download = `${(camera.code || camera.name || "camera").replace(/\s+/g, "_")}_${stamp}.png`
      link.href = canvas.toDataURL("image/png")
      link.click()
    } catch {
      /* cross-origin canvas may be tainted — ignore */
    }
  }

  return (
    <div
      className={cn(
        "overflow-hidden rounded-lg border border-border bg-black",
        isFullscreen && "fixed inset-0 z-[200] flex flex-col rounded-none border-0",
      )}
    >
      <div
        className={cn(
          "relative aspect-video w-full",
          isFullscreen && "flex-1 aspect-auto min-h-0",
        )}
      >
        {src && !error ? (
          <img
            ref={imgRef}
            src={src}
            alt={camera.name}
            className="h-full w-full object-contain"
            onError={() => {
              setError(true)
              window.setTimeout(() => {
                setError(false)
                setRetry((n) => n + 1)
              }, 2500)
            }}
          />
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-white/60">
            {error ? "Reconnecting…" : "No stream URL"}
          </div>
        )}

        <div className="absolute left-2 top-2 z-10 flex max-w-[70%] flex-wrap gap-1">
          <Badge className="max-w-full truncate bg-sky-700/90 text-white">
            {camera.server_name || "Server"}
          </Badge>
          {src && !error ? (
            <Badge className="bg-emerald-600/90 text-white">Live</Badge>
          ) : null}
        </div>

        <div className="absolute right-2 top-2 z-20 flex items-center gap-1">
          {canManage && onRemove ? (
            <Button
              type="button"
              size="icon"
              variant="ghost"
              className="h-8 w-8 bg-black/55 text-white hover:bg-red-700/80 hover:text-white"
              onClick={onRemove}
              disabled={removing}
              title="Remove camera"
              aria-label="Remove camera"
            >
              {removing ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Trash2 className="h-4 w-4" />
              )}
            </Button>
          ) : null}
          <Button
            type="button"
            size="icon"
            variant="ghost"
            className="h-8 w-8 bg-black/55 text-white hover:bg-black/75 hover:text-white"
            onClick={refreshStream}
            title="Refresh stream"
            aria-label="Refresh stream"
          >
            <RefreshCw className="h-4 w-4" />
          </Button>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            className="h-8 w-8 bg-black/55 text-white hover:bg-black/75 hover:text-white"
            onClick={takeSnapshot}
            title="Take snapshot"
            aria-label="Take snapshot"
            disabled={!src || error}
          >
            <Camera className="h-4 w-4" />
          </Button>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            className="h-8 w-8 bg-black/55 text-white hover:bg-black/75 hover:text-white"
            onClick={() => (isFullscreen ? exitFullscreen() : setIsFullscreen(true))}
            title={isFullscreen ? "Exit full screen (Esc)" : "View full screen"}
            aria-label={isFullscreen ? "Exit full screen" : "View full screen"}
          >
            {isFullscreen ? (
              <Minimize2 className="h-4 w-4" />
            ) : (
              <Maximize2 className="h-4 w-4" />
            )}
          </Button>
        </div>

        {(showTimestamp || isFullscreen) && (
          <span className="absolute bottom-12 right-2 z-10 rounded bg-black/60 px-1.5 py-0.5 text-[10px] text-white/90 sm:bottom-14">
            {now.toLocaleTimeString()}
          </span>
        )}

        <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent px-3 py-2">
          <p className="truncate text-sm font-medium text-white">{camera.name}</p>
          <p className="truncate text-xs text-white/70">
            {[camera.code, camera.status, camera.location_code || camera.location]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
      </div>

      {isFullscreen && (
        <div className="flex shrink-0 items-center justify-center gap-3 border-t border-white/10 bg-black/90 px-4 py-2 text-xs text-white/80">
          <span>
            {camera.name}
            {camera.server_name ? ` · ${camera.server_name}` : ""}
            {" · Press Esc or tap minimize to exit"}
          </span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-7 border-white/30 bg-transparent text-white hover:bg-white/10 hover:text-white"
            onClick={takeSnapshot}
          >
            <Camera className="mr-1.5 h-3.5 w-3.5" />
            Snapshot
          </Button>
        </div>
      )}
    </div>
  )
}

export default function AllCitiesCamerasPage() {
  const user = getStoredUser()
  const role = normalizeRole(user?.role)
  const allowed = role === "ADMIN" || role === "IT_SUPERADMIN"
  const canManage = role === "IT_SUPERADMIN"

  const [servers, setServers] = useState<ServerSummary[]>([])
  const [cameras, setCameras] = useState<CityCamera[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filterServerId, setFilterServerId] = useState<string>("all")
  const [layout, setLayout] = useState<GridLayout>("auto")
  const [showTimestamp, setShowTimestamp] = useState(true)
  const [wallFullscreen, setWallFullscreen] = useState(false)
  const [removingCameraKey, setRemovingCameraKey] = useState<string | null>(null)
  const [removingServerId, setRemovingServerId] = useState<number | null>(null)

  const load = useCallback(async (refresh = false) => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchAllCitiesStreams({ refresh })
      setServers(data.servers)
      setCameras(data.cameras)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load streams")
      setServers([])
      setCameras([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (allowed) void load(false)
  }, [allowed, load])

  useEffect(() => {
    if (!wallFullscreen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setWallFullscreen(false)
    }
    document.addEventListener("keydown", onKey)
    document.body.style.overflow = "hidden"
    return () => {
      document.removeEventListener("keydown", onKey)
      document.body.style.overflow = ""
    }
  }, [wallFullscreen])

  const onRemoveServer = async (server: ServerSummary) => {
    if (
      !window.confirm(
        `Remove "${server.name}" from Central Ops? Its cameras will disappear from All Cities.`
      )
    ) {
      return
    }
    setRemovingServerId(server.id)
    setError(null)
    try {
      await deleteRemoteServer(server.id)
      if (filterServerId === String(server.id)) setFilterServerId("all")
      await load(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove server")
    } finally {
      setRemovingServerId(null)
    }
  }

  const onRemoveCamera = async (cam: CityCamera) => {
    if (!cam.server_id) return
    const label = cam.name || cam.code || "this camera"
    if (
      !window.confirm(
        `Remove ${label} from ${cam.server_name || "this server"}? This deletes it on the node when possible.`
      )
    ) {
      return
    }
    const key = cam.ml_stream_key || cam.code || String(cam.id)
    setRemovingCameraKey(`${cam.server_id}-${key}`)
    setError(null)
    try {
      await removeServerCamera(cam.server_id, {
        stream_key: cam.ml_stream_key || cam.code,
        camera_id: cam.id,
        code: cam.code,
      })
      await load(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove camera")
    } finally {
      setRemovingCameraKey(null)
    }
  }

  const visibleCameras = useMemo(() => {
    if (filterServerId === "all") return cameras
    const id = Number(filterServerId)
    return cameras.filter((c) => c.server_id === id)
  }, [cameras, filterServerId])

  const grouped = useMemo(() => {
    const map = new Map<number, { server: ServerSummary | null; cameras: CityCamera[] }>()
    for (const s of servers) {
      map.set(s.id, { server: s, cameras: [] })
    }
    for (const cam of visibleCameras) {
      const sid = cam.server_id ?? 0
      if (!map.has(sid)) {
        map.set(sid, {
          server: {
            id: sid,
            name: cam.server_name || `Server ${sid}`,
            location_code: cam.location_code || "",
            connection_mode: "ml",
            ml_base_url: "",
            last_health: "",
            last_error: "",
            ok: true,
            source: "",
            error: "",
            camera_count: 0,
          },
          cameras: [],
        })
      }
      map.get(sid)!.cameras.push(cam)
    }
    return Array.from(map.values()).filter((g) => g.cameras.length > 0)
  }, [servers, visibleCameras])

  if (!allowed) {
    return <Navigate to={ROUTES.DASHBOARD} replace />
  }

  const cameraGrid = (
    <div className="space-y-8">
      {grouped.map(({ server, cameras: cams }) => (
        <section key={server?.id ?? "unknown"}>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Video className="h-4 w-4 text-muted-foreground" />
            <h2 className="text-base font-semibold text-foreground">{server?.name || "Server"}</h2>
            {server?.location_code ? (
              <Badge variant="outline">{server.location_code}</Badge>
            ) : null}
            <span className="text-xs text-muted-foreground">
              {cams.length} camera{cams.length === 1 ? "" : "s"}
              {server?.ml_base_url ? ` · ${server.ml_base_url}` : ""}
            </span>
            {server?.error ? (
              <span className="text-xs text-amber-700">{server.error}</span>
            ) : null}
            {canManage && server ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="ml-auto h-7 text-destructive hover:text-destructive"
                disabled={removingServerId === server.id}
                onClick={() => void onRemoveServer(server)}
              >
                {removingServerId === server.id ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Trash2 className="mr-1.5 h-3.5 w-3.5" />
                )}
                Remove server
              </Button>
            ) : null}
          </div>
          {cams.length === 0 ? (
            <p className="text-sm text-muted-foreground">No live cameras on this server.</p>
          ) : (
            <div className={cn("grid gap-3", GRID_CLASS[layout])}>
              {cams.map((cam) => {
                const removeKey = `${cam.server_id}-${cam.ml_stream_key || cam.code || cam.id}`
                return (
                  <StreamTile
                    key={`${cam.server_id}-${cam.id}-${cam.ml_stream_key || cam.code}`}
                    camera={cam}
                    showTimestamp={showTimestamp}
                    canManage={canManage}
                    onRemove={() => void onRemoveCamera(cam)}
                    removing={removingCameraKey === removeKey}
                  />
                )
              })}
            </div>
          )}
        </section>
      ))}
    </div>
  )

  return (
    <ModulePageLayout
      title="All Cities Cameras"
      description="Live detected streams from every connected Central Ops server."
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Select value={layout} onValueChange={(v) => setLayout(v as GridLayout)}>
            <SelectTrigger className="h-8 w-[7.5rem]" aria-label="Grid layout">
              <SelectValue placeholder="Layout" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="auto">Auto grid</SelectItem>
              <SelectItem value="1">1 column</SelectItem>
              <SelectItem value="2">2 columns</SelectItem>
              <SelectItem value="3">3 columns</SelectItem>
              <SelectItem value="4">4 columns</SelectItem>
            </SelectContent>
          </Select>
          <Button
            type="button"
            variant={showTimestamp ? "secondary" : "outline"}
            size="sm"
            onClick={() => setShowTimestamp((v) => !v)}
          >
            Timestamp
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setWallFullscreen(true)}
            disabled={cameras.length === 0}
          >
            <Expand className="mr-2 h-4 w-4" />
            Wall view
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void load(true)}
            disabled={loading}
          >
            {loading ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="mr-2 h-4 w-4" />
            )}
            Refresh live
          </Button>
        </div>
      }
    >
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-muted-foreground">Connected servers:</span>
        {servers.length === 0 && !loading ? (
          <span className="text-sm text-muted-foreground">None — connect them in Central Ops</span>
        ) : (
          servers.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() =>
                setFilterServerId((prev) => (prev === String(s.id) ? "all" : String(s.id)))
              }
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
                filterServerId === String(s.id)
                  ? "border-sky-600 bg-sky-50 text-sky-900"
                  : "border-border bg-background hover:bg-muted",
              )}
            >
              {s.ok || s.last_health === "ok" ? (
                <Wifi className="h-3.5 w-3.5 text-emerald-600" />
              ) : (
                <WifiOff className="h-3.5 w-3.5 text-amber-600" />
              )}
              {s.name}
              <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">
                {s.camera_count}
              </Badge>
            </button>
          ))
        )}
        {filterServerId !== "all" && (
          <Button type="button" variant="ghost" size="sm" onClick={() => setFilterServerId("all")}>
            Show all
          </Button>
        )}
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {loading && cameras.length === 0 ? (
        <div className="flex items-center justify-center gap-2 py-24 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
          Loading streams from connected servers…
        </div>
      ) : cameras.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-3 py-24 text-muted-foreground">
          <Server className="h-10 w-10 opacity-40" />
          <p className="text-sm">No cameras yet. Connect ML servers in Central Ops first.</p>
          <Button type="button" variant="outline" size="sm" asChild>
            <Link to={ROUTES.OPS_CENTRAL}>Open Central Ops</Link>
          </Button>
        </div>
      ) : (
        cameraGrid
      )}

      {wallFullscreen && cameras.length > 0 && (
        <div className="fixed inset-0 z-[190] flex flex-col bg-black">
          <div className="flex shrink-0 items-center justify-between gap-3 border-b border-white/10 px-4 py-2">
            <p className="text-sm font-medium text-white">
              All Cities Wall · {visibleCameras.length} camera
              {visibleCameras.length === 1 ? "" : "s"}
            </p>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-8 border-white/30 bg-transparent text-white hover:bg-white/10 hover:text-white"
                onClick={() => void load(true)}
                disabled={loading}
              >
                <RefreshCw className={cn("mr-1.5 h-3.5 w-3.5", loading && "animate-spin")} />
                Refresh
              </Button>
              <Button
                type="button"
                size="sm"
                className="h-8"
                onClick={() => setWallFullscreen(false)}
              >
                <Minimize2 className="mr-1.5 h-3.5 w-3.5" />
                Exit wall (Esc)
              </Button>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-3">{cameraGrid}</div>
        </div>
      )}
    </ModulePageLayout>
  )
}
