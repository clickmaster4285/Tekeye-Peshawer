import { useState } from "react"
import { Link, useParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { ArrowLeft, Camera, Clock3, Film, MapPin } from "lucide-react"
import { ModulePageLayout } from "@/components/dashboard/module-page-layout"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ROUTES } from "@/routes/config"
import { TrackingCaptureThumb } from "@/components/object-tracking/tracking-capture-thumb"
import {
  MovementClipDialog,
  MovementFrame,
  MovementSummary,
  PlayClipButton,
} from "@/components/object-tracking/movement-clip"
import {
  fetchTrackedObjectDetail,
  formatDuration,
  objectTypeLabel,
  type ObjectMovementWithClip,
} from "@/lib/object-tracking-api"

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—"
  try {
    return new Date(iso).toLocaleString("en-GB", {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    })
  } catch {
    return iso
  }
}

export default function ObjectTrackingDetailPage() {
  const { uuid = "" } = useParams()

  const detailQuery = useQuery({
    queryKey: ["object-tracking-detail", uuid],
    queryFn: () => fetchTrackedObjectDetail(uuid),
    enabled: Boolean(uuid)
  })

  const [playing, setPlaying] = useState<ObjectMovementWithClip | null>(null)

  const obj = detailQuery.data
  const visits = obj?.visits ?? []
  const tracks = obj?.tracks ?? []
  const movements = obj?.movements ?? []

  return (
    <ModulePageLayout
      title={obj?.code || "Object detail"}
      description="Global identity timeline with visits, tracks, entry/exit and duration."
      actions={
        <Button asChild variant="outline" size="sm">
          <Link to={ROUTES.OBJECT_TRACKING}>
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back
          </Link>
        </Button>
      }
    >
      {detailQuery.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : detailQuery.isError || !obj ? (
        <p className="text-sm text-destructive">Could not load this tracked object.</p>
      ) : (
        <div className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Identity</CardDescription>
                <CardTitle className="text-2xl flex items-center gap-2">
                  {obj.code}
                  <Badge variant="secondary">{objectTypeLabel(obj.object_type)}</Badge>
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm capitalize">{obj.class_name || obj.label || "—"}</CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Presence</CardDescription>
                <CardTitle className="text-2xl">{obj.is_present ? "Present" : "Exited"}</CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground flex items-center gap-2">
                <Camera className="h-4 w-4" />
                {obj.latest_camera_name || "—"}
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>First / last seen</CardDescription>
                <CardTitle className="text-base">{formatDateTime(obj.first_seen_at)}</CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground">
                Last {formatDateTime(obj.last_seen_at)}
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Current visit duration</CardDescription>
                <CardTitle className="text-2xl flex items-center gap-2">
                  <Clock3 className="h-5 w-5" />
                  {obj.is_present
                    ? formatDuration(
                        Math.max(0, (Date.now() - new Date(obj.entry_at).getTime()) / 1000),
                      )
                    : formatDuration(obj.duration_seconds)}
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground">
                Visits: {visits.length}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Primary capture</CardTitle>
              <CardDescription>First saved snapshot for this global identity</CardDescription>
            </CardHeader>
            <CardContent>
              <TrackingCaptureThumb
                url={obj.snapshot_url}
                alt={obj.code}
                size="lg"
                className="h-56 w-full max-w-xl rounded-md border object-contain bg-muted/30"
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Film className="h-4 w-4" />
                Movement clips
              </CardTitle>
              <CardDescription>
                While it stands still this object has one snapshot. Each time it moves, a clip is recorded
                (newest first).
              </CardDescription>
            </CardHeader>
            <CardContent>
              {movements.length === 0 ? (
                <p className="text-sm text-muted-foreground">No movement recorded for this object yet.</p>
              ) : (
                <div className="space-y-3">
                  {movements.map((m) => (
                    <div key={m.id} className="flex flex-col gap-3 rounded-md border p-3 sm:flex-row sm:items-center">
                      <button
                        type="button"
                        className="w-full shrink-0 sm:w-56"
                        onClick={() => setPlaying(m)}
                        aria-label="Play movement clip"
                      >
                        <MovementFrame
                          url={m.clip_detail.poster_url}
                          movements={[m]}
                          sourceWidth={m.clip_detail.source_width}
                          sourceHeight={m.clip_detail.source_height}
                          alt={`Movement ${m.id}`}
                        />
                      </button>
                      <div className="min-w-0 flex-1 space-y-1.5">
                        <p className="flex flex-wrap items-center gap-x-3 text-sm text-muted-foreground">
                          <span className="inline-flex items-center gap-1">
                            <Camera className="h-3.5 w-3.5" />
                            {m.clip_detail.camera_name || "Camera"}
                          </span>
                          <span>{formatDateTime(m.started_at)}</span>
                        </p>
                        <MovementSummary movement={m} />
                        <PlayClipButton onClick={() => setPlaying(m)} label="Play clip" />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Visit timeline</CardTitle>
              <CardDescription>
                Each leave/return creates a new visit with its own entry, exit, duration and capture.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Capture</TableHead>
                    <TableHead>#</TableHead>
                    <TableHead>Camera</TableHead>
                    <TableHead>Local track</TableHead>
                    <TableHead>Entry</TableHead>
                    <TableHead>Last seen</TableHead>
                    <TableHead>Exit</TableHead>
                    <TableHead>Duration</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {visits.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={9} className="text-center text-muted-foreground">
                        No visits yet.
                      </TableCell>
                    </TableRow>
                  ) : (
                    visits.map((v) => (
                      <TableRow key={v.id}>
                        <TableCell>
                          <TrackingCaptureThumb url={v.snapshot_url} alt={`${obj.code} visit ${v.id}`} size="sm" />
                        </TableCell>
                        <TableCell>{v.id}</TableCell>
                        <TableCell>{v.camera_name || "—"}</TableCell>
                        <TableCell>#{v.local_track_id ?? "—"}</TableCell>
                        <TableCell className="whitespace-nowrap">{formatDateTime(v.entry_at)}</TableCell>
                        <TableCell className="whitespace-nowrap">{formatDateTime(v.last_seen_at)}</TableCell>
                        <TableCell className="whitespace-nowrap">{formatDateTime(v.exit_at)}</TableCell>
                        <TableCell>
                          {v.status === "active"
                            ? formatDuration(
                                Math.max(0, (Date.now() - new Date(v.entry_at).getTime()) / 1000),
                              )
                            : formatDuration(v.duration_seconds)}
                        </TableCell>
                        <TableCell>
                          <Badge variant={v.status === "active" ? "default" : "outline"}>
                            {v.status}
                          </Badge>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">ByteTrack sessions</CardTitle>
              <CardDescription>Local track IDs linked to this global identity</CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Track ID</TableHead>
                    <TableHead>Camera</TableHead>
                    <TableHead>Started</TableHead>
                    <TableHead>Ended</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {tracks.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={5} className="text-center text-muted-foreground">
                        No track sessions.
                      </TableCell>
                    </TableRow>
                  ) : (
                    tracks.map((t) => (
                      <TableRow key={t.id}>
                        <TableCell>#{t.local_track_id}</TableCell>
                        <TableCell>{t.camera_name || "—"}</TableCell>
                        <TableCell className="whitespace-nowrap">{formatDateTime(t.started_at)}</TableCell>
                        <TableCell className="whitespace-nowrap">{formatDateTime(t.ended_at)}</TableCell>
                        <TableCell>
                          <Badge variant={t.status === "active" ? "default" : "outline"}>
                            {t.status}
                          </Badge>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Camera history</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {(obj.camera_history || []).length === 0 ? (
                <p className="text-sm text-muted-foreground">No camera history yet.</p>
              ) : (
                (obj.camera_history || []).slice().reverse().map((row, idx) => {
                  const camName =
                    (row.camera_name || "").trim() ||
                    (row.camera_code || "").trim() ||
                    visits.find((v) => v.camera === row.camera_id)?.camera_name ||
                    tracks.find((t) => t.camera === row.camera_id)?.camera_name ||
                    obj.latest_camera_name ||
                    "Camera"
                  return (
                  <div key={`${row.camera_id}-${row.at}-${idx}`} className="text-sm flex items-center gap-2">
                    <MapPin className="h-3.5 w-3.5 text-muted-foreground" />
                    {camName} · {formatDateTime(row.at)}
                  </div>
                  )
                })
              )}
            </CardContent>
          </Card>
        </div>
      )}
      <MovementClipDialog
        clip={playing?.clip_detail ?? null}
        movements={playing ? [playing] : []}
        open={playing !== null}
        onOpenChange={(open) => {
          if (!open) setPlaying(null)
        }}
      />
    </ModulePageLayout>
  )
}
