import { useEffect, useState } from "react"
import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { Camera, ChevronLeft, ChevronRight, Clock3, Film, RefreshCw, Search } from "lucide-react"
import { ModulePageLayout } from "@/components/dashboard/module-page-layout"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  MovementClipDialog,
  MovementFrame,
  MovementSummary,
  PlayClipButton,
  formatClipTime,
} from "@/components/object-tracking/movement-clip"
import { fetchCameras } from "@/lib/cameras-api"
import {
  fetchMotionClips,
  formatDuration,
  type MotionClipRecord,
  type ObjectType,
} from "@/lib/object-tracking-api"

const PAGE_SIZE = 24

export default function MovementClipsPage() {
  const [search, setSearch] = useState("")
  const [debouncedSearch, setDebouncedSearch] = useState("")
  const [camera, setCamera] = useState<string>("all")
  const [objectType, setObjectType] = useState<"all" | ObjectType>("all")
  const [dateFrom, setDateFrom] = useState("")
  const [dateTo, setDateTo] = useState("")
  const [page, setPage] = useState(1)
  const [playing, setPlaying] = useState<MotionClipRecord | null>(null)

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 300)
    return () => window.clearTimeout(timer)
  }, [search])

  useEffect(() => {
    setPage(1)
  }, [debouncedSearch, camera, objectType, dateFrom, dateTo])

  const camerasQuery = useQuery({
    queryKey: ["movement-clips-cameras"],
    queryFn: () => fetchCameras(),
    staleTime: 5 * 60 * 1000,
  })

  const clipsQuery = useQuery({
    queryKey: ["object-tracking-motion-clips", debouncedSearch, camera, objectType, dateFrom, dateTo, page],
    queryFn: () =>
      fetchMotionClips({
        q: debouncedSearch || undefined,
        camera: camera === "all" ? "all" : Number(camera),
        object_type: objectType,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        page,
        page_size: PAGE_SIZE,
      }),
    placeholderData: keepPreviousData,
    refetchInterval: 15000,
  })

  const clips = clipsQuery.data?.results ?? []
  const total = clipsQuery.data?.count ?? 0
  const totalPages = clipsQuery.data?.total_pages ?? 1

  return (
    <ModulePageLayout
      title="Movement Clips"
      description="Video recorded when an object starts moving: 5 s before the movement, until it stops (10–30 s per clip)."
      actions={
        <Button variant="outline" size="sm" onClick={() => clipsQuery.refetch()} disabled={clipsQuery.isFetching}>
          <RefreshCw className={`mr-2 h-4 w-4 ${clipsQuery.isFetching ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      }
    >
      <div className="space-y-4">
        <Card>
          <CardContent className="grid gap-3 pt-6 sm:grid-cols-2 lg:grid-cols-5">
            <div className="relative lg:col-span-2">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Object ID, class or camera…"
                className="pl-8"
              />
            </div>
            <Select value={camera} onValueChange={setCamera}>
              <SelectTrigger>
                <SelectValue placeholder="Camera" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All cameras</SelectItem>
                {(camerasQuery.data ?? []).map((c) => (
                  <SelectItem key={c.id} value={String(c.id)}>
                    {c.name || c.code}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={objectType} onValueChange={(v) => setObjectType(v as "all" | ObjectType)}>
              <SelectTrigger>
                <SelectValue placeholder="Object type" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All objects</SelectItem>
                <SelectItem value="person">Persons</SelectItem>
                <SelectItem value="vehicle">Vehicles</SelectItem>
                <SelectItem value="object">Other objects</SelectItem>
              </SelectContent>
            </Select>
            <div className="flex items-center gap-2">
              <Input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} aria-label="From date" />
              <Input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} aria-label="To date" />
            </div>
          </CardContent>
        </Card>

        {clipsQuery.isLoading ? (
          <p className="text-sm text-muted-foreground">Loading clips…</p>
        ) : clipsQuery.isError ? (
          <p className="text-sm text-destructive">Could not load movement clips.</p>
        ) : clips.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center gap-2 py-12 text-center text-muted-foreground">
              <Film className="h-8 w-8" />
              <p>No movement clips yet.</p>
              <p className="text-xs">Clips appear here a few seconds after an object stops moving.</p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {clips.map((clip) => (
              <Card key={clip.id} className="overflow-hidden">
                <button
                  type="button"
                  className="group relative block w-full text-left"
                  onClick={() => setPlaying(clip)}
                  aria-label="Play clip"
                >
                  <MovementFrame
                    url={clip.poster_url}
                    movements={clip.movements}
                    sourceWidth={clip.source_width}
                    sourceHeight={clip.source_height}
                    alt={`Clip ${clip.id}`}
                    className="rounded-none border-0"
                  />
                  <span className="absolute inset-0 flex items-center justify-center bg-black/0 transition group-hover:bg-black/30">
                    <span className="rounded-full bg-black/60 p-3 text-white opacity-80 group-hover:opacity-100">
                      <Film className="h-6 w-6" />
                    </span>
                  </span>
                  <Badge className="absolute bottom-2 right-2" variant="secondary">
                    {formatDuration(clip.duration_seconds)}
                  </Badge>
                </button>
                <CardContent className="space-y-2 p-4">
                  <div className="flex items-center justify-between gap-2 text-sm">
                    <span className="inline-flex items-center gap-1 font-medium">
                      <Camera className="h-4 w-4" />
                      {clip.camera_name || clip.camera_key || "Camera"}
                    </span>
                    <span className="inline-flex items-center gap-1 text-muted-foreground">
                      <Clock3 className="h-3.5 w-3.5" />
                      {formatClipTime(clip.started_at)}
                    </span>
                  </div>
                  <div className="space-y-1.5">
                    {clip.movements.map((m) => (
                      <MovementSummary key={m.id} movement={m} />
                    ))}
                  </div>
                  <PlayClipButton onClick={() => setPlaying(clip)} />
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-muted-foreground">
            {total === 0 ? "No results" : `${total} clip${total === 1 ? "" : "s"} · Page ${page} of ${totalPages}`}
          </p>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1 || clipsQuery.isFetching}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="gap-1"
            >
              <ChevronLeft className="h-4 w-4" />
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages || clipsQuery.isFetching || total === 0}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              className="gap-1"
            >
              Next
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>

      <MovementClipDialog
        clip={playing ? { ...playing, camera_name: playing.camera_name || playing.camera_key } : null}
        movements={playing?.movements ?? []}
        open={playing !== null}
        onOpenChange={(open) => {
          if (!open) setPlaying(null)
        }}
      />
    </ModulePageLayout>
  )
}
