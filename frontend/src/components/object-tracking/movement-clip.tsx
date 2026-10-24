import { useId } from "react"
import { Link } from "react-router-dom"
import { ArrowRight, Camera, Clock3, Film, Play } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { resolveMediaUrl } from "@/lib/cameras-api"
import {
  directionLabel,
  formatDuration,
  type MotionClipBrief,
  type ObjectMovementRecord,
} from "@/lib/object-tracking-api"
import { getObjectTrackingDetailPath } from "@/routes/config"

export function formatClipTime(iso: string | null | undefined): string {
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

function center(b: number[]): [number, number] {
  return [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2]
}

/** Frame image with each movement drawn on it: dashed box = where it rested, solid box + arrow = where it went. */
export function MovementFrame({
  url,
  movements,
  sourceWidth,
  sourceHeight,
  alt,
  className = "",
}: {
  url?: string
  movements: ObjectMovementRecord[]
  sourceWidth: number
  sourceHeight: number
  alt: string
  className?: string
}) {
  const markerId = useId().replace(/:/g, "")
  const w = sourceWidth || 1280
  const h = sourceHeight || 720
  const src = url ? resolveMediaUrl(url) : ""
  return (
    <div
      className={`relative overflow-hidden rounded-md border bg-muted ${className}`}
      style={{ aspectRatio: `${w} / ${h}` }}
    >
      {src ? (
        <img src={src} alt={alt} className="absolute inset-0 h-full w-full object-fill" loading="lazy" />
      ) : (
        <div className="absolute inset-0 flex items-center justify-center text-xs text-muted-foreground">
          No image
        </div>
      )}
      <svg
        className="pointer-events-none absolute inset-0 h-full w-full"
        viewBox={`0 0 ${w} ${h}`}
        preserveAspectRatio="none"
        aria-hidden
      >
        <defs>
          <marker id={markerId} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto">
            <path d="M0,0 L10,5 L0,10 z" className="fill-amber-400" />
          </marker>
        </defs>
        {movements.map((m) => {
          if (m.from_bbox.length < 4 || m.to_bbox.length < 4) return null
          const [fx, fy] = center(m.from_bbox)
          const [tx, ty] = center(m.to_bbox)
          const [x1, y1, x2, y2] = m.from_bbox
          const [a1, b1, a2, b2] = m.to_bbox
          return (
            <g key={m.id}>
              <rect
                x={x1}
                y={y1}
                width={x2 - x1}
                height={y2 - y1}
                className="fill-none stroke-sky-400"
                strokeWidth={2}
                strokeDasharray="6 4"
                vectorEffect="non-scaling-stroke"
              />
              <rect
                x={a1}
                y={b1}
                width={a2 - a1}
                height={b2 - b1}
                className="fill-none stroke-amber-400"
                strokeWidth={2}
                vectorEffect="non-scaling-stroke"
              />
              <line
                x1={fx}
                y1={fy}
                x2={tx}
                y2={ty}
                className="stroke-amber-400"
                strokeWidth={3}
                vectorEffect="non-scaling-stroke"
                markerEnd={`url(#${markerId})`}
              />
            </g>
          )
        })}
      </svg>
    </div>
  )
}

function objectName(m: ObjectMovementRecord): string {
  return m.global_code || m.ml_object_id || m.class_name || "Object"
}

export function MovementSummary({ movement }: { movement: ObjectMovementRecord }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      {movement.global_uuid ? (
        <Link
          to={getObjectTrackingDetailPath(movement.global_uuid)}
          className="font-medium text-primary hover:underline"
          onClick={(e) => e.stopPropagation()}
        >
          {objectName(movement)}
        </Link>
      ) : (
        <span className="font-medium">{objectName(movement)}</span>
      )}
      <span className="capitalize text-muted-foreground">{movement.class_name}</span>
      <Badge variant="outline">{directionLabel(movement.direction)}</Badge>
      <span className="text-muted-foreground">
        {Math.round(movement.distance_px)} px ({movement.distance_pct}% of view)
      </span>
      <span className="text-muted-foreground">· {formatDuration(movement.duration_seconds)}</span>
      {movement.still_moving ? <Badge variant="secondary">Still moving — continues in next clip</Badge> : null}
    </div>
  )
}

/** Video player + before / after frames for one clip. */
export function MovementClipDialog({
  clip,
  movements,
  open,
  onOpenChange,
}: {
  clip: MotionClipBrief | null
  movements: ObjectMovementRecord[]
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-4xl">
        {clip ? (
          <>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <Film className="h-5 w-5" />
                Movement clip
                {clip.part > 1 ? <Badge variant="secondary">Part {clip.part}</Badge> : null}
              </DialogTitle>
              <DialogDescription className="flex flex-wrap items-center gap-x-4 gap-y-1">
                <span className="inline-flex items-center gap-1">
                  <Camera className="h-3.5 w-3.5" />
                  {clip.camera_name || "Camera"}
                </span>
                <span className="inline-flex items-center gap-1">
                  <Clock3 className="h-3.5 w-3.5" />
                  {formatClipTime(clip.started_at)} · {formatDuration(clip.duration_seconds)}
                </span>
              </DialogDescription>
            </DialogHeader>
            {clip.video_url ? (
              <video
                key={clip.video_url}
                src={resolveMediaUrl(clip.video_url)}
                poster={clip.poster_url ? resolveMediaUrl(clip.poster_url) : undefined}
                controls
                autoPlay
                playsInline
                className="w-full rounded-md border bg-black"
              />
            ) : (
              <p className="text-sm text-muted-foreground">Video file is not available.</p>
            )}
            <div className="grid items-center gap-3 sm:grid-cols-[1fr_auto_1fr]">
              <div className="space-y-1">
                <p className="text-xs font-medium text-muted-foreground">Before — movement started</p>
                <MovementFrame
                  url={clip.poster_url}
                  movements={movements}
                  sourceWidth={clip.source_width}
                  sourceHeight={clip.source_height}
                  alt="Before movement"
                />
              </div>
              <ArrowRight className="mx-auto hidden h-5 w-5 text-muted-foreground sm:block" />
              <div className="space-y-1">
                <p className="text-xs font-medium text-muted-foreground">After — end of clip</p>
                <MovementFrame
                  url={clip.end_frame_url}
                  movements={[]}
                  sourceWidth={clip.source_width}
                  sourceHeight={clip.source_height}
                  alt="After movement"
                />
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              Dashed blue box: where the object was resting. Orange box and arrow: where it moved to.
            </p>
            <div className="space-y-2">
              {movements.map((m) => (
                <MovementSummary key={m.id} movement={m} />
              ))}
            </div>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

export function PlayClipButton({ onClick, label = "Play" }: { onClick: () => void; label?: string }) {
  return (
    <Button size="sm" variant="outline" className="gap-1" onClick={onClick}>
      <Play className="h-3.5 w-3.5" />
      {label}
    </Button>
  )
}
