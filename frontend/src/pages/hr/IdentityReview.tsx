import { useMemo, useState, type Dispatch, type SetStateAction } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, HelpCircle, Images, Loader2, Play, RefreshCw, ShieldCheck, UserX, Users, X } from "lucide-react"
import { ModulePageLayout } from "@/components/dashboard/module-page-layout"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useToast } from "@/hooks/use-toast"
import { resolveMediaUrl } from "@/lib/cameras-api"
import {
  identityApi,
  MODEL_LABEL,
  type DecisionFilters,
  type ClusterStatus,
  type GalleryEntry,
  type UnknownCluster as UnknownClusterRow,
  type IdentityDecision,
  type IdentityProfile,
  type RecognitionMode,
} from "@/lib/identity-api"
import { ROUTES } from "@/routes/config"

const MODE_LABEL: Record<RecognitionMode, string> = {
  manual: "Manual",
  assisted: "Assisted",
  automatic: "Automatic",
}

const MODE_HELP: Record<RecognitionMode, string> = {
  manual: "Sightings are logged only — HR marks attendance by hand.",
  assisted: "Daily check-in waits for your approval; later sightings update last-seen.",
  automatic: "Recognized on an attendance camera → attendance marked immediately.",
}

type Factors = {
  face_similarity?: number
  best_entry_similarity?: number | null
  centroid_similarity?: number | null
  second_best_similarity?: number | null
  margin?: number
  quality?: number | null
  track_consistency?: number | null
  ml_label?: string | null
  gallery_size?: number
  thresholds?: Partial<
    Record<"accept_similarity" | "review_similarity" | "accept_confidence" | "min_margin" | "min_quality", number>
  >
  quality_detail?: {
    face_px?: number
    blur?: number
    yaw?: number | null
    brightness?: number
    reasons?: string[]
  } | null
}

type OpenById = Dispatch<SetStateAction<number | null>>

const pct = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v * 100)}%`)
const num = (v: unknown, digits = 2) => (typeof v === "number" ? v.toFixed(digits) : "—")
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "—")

function FaceImg({
  url,
  alt,
  className = "h-28 w-24",
}: {
  url: string | null | undefined
  alt: string
  className?: string
}) {
  const src = url ? resolveMediaUrl(url) : ""
  if (!src) {
    return (
      <div
        className={`${className} flex items-center justify-center rounded border bg-muted text-[10px] text-muted-foreground`}
      >
        No image
      </div>
    )
  }
  return (
    <a href={src} target="_blank" rel="noopener noreferrer" className="shrink-0">
      <img src={src} alt={alt} loading="lazy" className={`${className} rounded border bg-muted object-cover`} />
    </a>
  )
}

function OutcomeBadge({ outcome }: { outcome: IdentityDecision["outcome"] }) {
  if (outcome === "accepted") return <Badge className="bg-emerald-600 hover:bg-emerald-600">Accepted</Badge>
  if (outcome === "review") return <Badge className="bg-amber-500 hover:bg-amber-500">Needs review</Badge>
  return <Badge variant="secondary">Unknown</Badge>
}

function ReviewBadge({ status }: { status: IdentityDecision["review_status"] }) {
  if (status === "pending")
    return (
      <Badge variant="outline" className="border-amber-500 text-amber-600">
        Pending
      </Badge>
    )
  if (status === "approved")
    return (
      <Badge variant="outline" className="border-emerald-600 text-emerald-700">
        Approved
      </Badge>
    )
  if (status === "rejected")
    return (
      <Badge variant="outline" className="border-red-500 text-red-600">
        Rejected
      </Badge>
    )
  return <span className="text-xs text-muted-foreground">—</span>
}

// ── "Why?" dialog ─────────────────────────────────────────────────────────

function WhyDialog({ decisionId, onClose }: { decisionId: number | null; onClose: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ["identity", "decision", decisionId],
    queryFn: () => identityApi.decision(decisionId as number),
    enabled: decisionId != null,
  })
  const f = (data?.factors || {}) as Factors
  const q = f.quality_detail || {}
  const t = f.thresholds || {}

  return (
    <Dialog open={decisionId != null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Why this decision? #{decisionId}</DialogTitle>
          <DialogDescription>
            Every factor the identity engine used, and each attendance rule it checked.
          </DialogDescription>
        </DialogHeader>
        {isLoading || !data ? (
          <div className="flex justify-center py-10">
            <Loader2 className="h-6 w-6 animate-spin" />
          </div>
        ) : (
          <div className="space-y-5 text-sm">
            <div className="flex flex-wrap items-start gap-4">
              <div className="space-y-1 text-center">
                <FaceImg url={data.snapshot_url} alt="Live face" className="h-36 w-32" />
                <div className="text-xs text-muted-foreground">Live face</div>
              </div>
              <div className="space-y-1 text-center">
                <FaceImg url={data.matched_entry_image_url} alt="Matched gallery face" className="h-36 w-32" />
                <div className="text-xs text-muted-foreground">Closest gallery photo</div>
              </div>
              <div className="min-w-[14rem] flex-1 space-y-1">
                <div className="flex items-center gap-2">
                  <OutcomeBadge outcome={data.outcome} />
                  <ReviewBadge status={data.review_status} />
                </div>
                <div className="text-base font-semibold">{data.staff_name || "No employee"}</div>
                <div className="text-muted-foreground">
                  {data.camera_name || data.source} · {when(data.created_at)}
                </div>
                <div className="text-xs text-muted-foreground">
                  {MODEL_LABEL[data.model_name] || data.model_name}
                  {data.track_id != null ? ` · track ${data.track_id}` : ""}
                </div>
                <div className="pt-1">{data.reason}</div>
                {data.reviewed_by_name && (
                  <div className="text-xs text-muted-foreground">
                    Reviewed by {data.reviewed_by_name} at {when(data.reviewed_at)}
                    {data.review_note ? ` — “${data.review_note}”` : ""}
                  </div>
                )}
              </div>
            </div>

            <div>
              <div className="mb-2 font-medium">Identity factors</div>
              <Table>
                <TableBody>
                  <TableRow>
                    <TableCell>Face similarity (blended)</TableCell>
                    <TableCell className="font-mono">{num(f.face_similarity, 3)}</TableCell>
                    <TableCell className="text-muted-foreground">
                      accept ≥ {num(t.accept_similarity)}, review ≥ {num(t.review_similarity)}
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell>Best single gallery photo / employee centroid</TableCell>
                    <TableCell className="font-mono">
                      {num(f.best_entry_similarity, 3)} / {num(f.centroid_similarity, 3)}
                    </TableCell>
                    <TableCell className="text-muted-foreground">{f.gallery_size ?? 0} photos in gallery</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell>Margin over next-closest employee</TableCell>
                    <TableCell className="font-mono">{num(f.margin, 3)}</TableCell>
                    <TableCell className="text-muted-foreground">
                      runner-up {num(f.second_best_similarity, 3)} · min {num(t.min_margin)}
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell>Face quality</TableCell>
                    <TableCell className="font-mono">{num(f.quality, 2)}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {f.quality == null
                        ? "not scored by this model — factor excluded"
                        : `size ${q.face_px ?? "—"}px · sharpness ${num(q.blur, 0)} · yaw ${q.yaw ?? "—"}° · light ${num(
                            q.brightness,
                            0
                          )}${Array.isArray(q.reasons) && q.reasons.length ? ` · ${q.reasons.join(", ")}` : ""}`}
                    </TableCell>
                  </TableRow>
                  {f.ml_label !== undefined && (
                    <TableRow>
                      <TableCell>ML service label (evidence only)</TableCell>
                      <TableCell className="font-mono">{f.ml_label || "—"}</TableCell>
                      <TableCell className="text-muted-foreground">does not decide identity on its own</TableCell>
                    </TableRow>
                  )}
                  <TableRow>
                    <TableCell>Track consistency</TableCell>
                    <TableCell className="font-mono">
                      {f.track_consistency == null ? "—" : pct(f.track_consistency)}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {data.track_id != null ? `track ${data.track_id}` : "no tracker on this source"}
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell className="font-medium">Combined confidence</TableCell>
                    <TableCell className="font-mono font-medium">{num(data.confidence, 3)}</TableCell>
                    <TableCell className="text-muted-foreground">accept ≥ {num(t.accept_confidence)}</TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </div>

            {!!data.policy?.gates?.length && (
              <div>
                <div className="mb-2 font-medium">Attendance rules</div>
                <div className="space-y-1">
                  {data.policy.gates.map((g, i) => (
                    <div key={i} className="flex items-start gap-2">
                      {g.passed === true ? (
                        <Check className="mt-0.5 h-4 w-4 text-emerald-600" />
                      ) : g.passed === false ? (
                        <X className="mt-0.5 h-4 w-4 text-red-500" />
                      ) : (
                        <HelpCircle className="mt-0.5 h-4 w-4 text-muted-foreground" />
                      )}
                      <span className="w-32 shrink-0 capitalize">{g.gate.replace(/_/g, " ")}</span>
                      <span className="text-muted-foreground">{g.detail}</span>
                    </div>
                  ))}
                </div>
                <div className="mt-2 text-muted-foreground">
                  Result: <span className="font-medium text-foreground">{data.policy.message}</span>
                  {data.attendance_action ? ` (attendance: ${data.attendance_action.replace(/_/g, " ")})` : ""}
                </div>
              </div>
            )}

            {!!data.candidate_gallery?.length && (
              <div>
                <div className="mb-2 font-medium">{data.staff_name}’s gallery</div>
                <div className="flex flex-wrap gap-2">
                  {data.candidate_gallery.map((e) => (
                    <FaceImg key={e.id} url={e.image_url} alt="Gallery" className="h-20 w-16" />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

// ── review queue ──────────────────────────────────────────────────────────

function ReviewCard({ d, employees, onWhy }: { d: IdentityDecision; employees: IdentityProfile[]; onWhy: OpenById }) {
  const { toast } = useToast()
  const qc = useQueryClient()
  const isCluster = d.source === "cluster"
  const isJourney = d.source === "journey" || isCluster
  const clusterInfo = (d.factors as { cluster?: { code?: string; observations?: number; cameras?: number } }).cluster
  // Journey/cluster sightings come from any camera — attendance stays opt-in for them.
  const [markAttendance, setMarkAttendance] = useState(!isJourney)
  const [addToGallery, setAddToGallery] = useState(d.can_add_to_gallery)
  const [otherStaff, setOtherStaff] = useState<string>("")
  const [note, setNote] = useState("")

  const done = () => {
    void qc.invalidateQueries({ queryKey: ["identity"] })
  }
  const approve = useMutation({
    mutationFn: (staffId?: number) =>
      identityApi.approve(d.id, {
        staff_id: staffId,
        mark_attendance: markAttendance,
        add_to_gallery: addToGallery,
        note,
      }),
    onSuccess: (res) => {
      const parts = [
        res.attendance ? `attendance: ${res.attendance.action.replace(/_/g, " ")}` : null,
        res.gallery ? res.gallery.message : null,
        res.journey?.person_code ? `journey linked (${res.journey.person_code})` : null,
        res.journey?.merged_persons?.length
          ? `${res.journey.merged_persons.length} journey(s) merged into ${res.journey.journey_person_code}`
          : null,
        res.journey?.gallery_added ? `${res.journey.gallery_added} face(s) added to gallery` : null,
      ].filter(Boolean)
      toast({
        title: `Approved — ${res.decision.staff_name}`,
        description: parts.join(" · "),
      })
      done()
    },
    onError: (e: Error) =>
      toast({
        title: "Approve failed",
        description: e.message,
        variant: "destructive",
      }),
  })
  const reject = useMutation({
    mutationFn: () => identityApi.reject(d.id, note),
    onSuccess: () => {
      toast({
        title: "Rejected",
        description: "Not counted as this employee.",
      })
      done()
    },
    onError: (e: Error) =>
      toast({
        title: "Reject failed",
        description: e.message,
        variant: "destructive",
      }),
  })
  const busy = approve.isPending || reject.isPending
  const isCheckin = d.policy?.action === "assisted_pending"

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex gap-3">
          <div className="space-y-1 text-center">
            <FaceImg url={d.snapshot_url} alt="Live face" />
            <div className="text-[10px] text-muted-foreground">Live</div>
          </div>
          <div className="space-y-1 text-center">
            <FaceImg url={d.matched_entry_image_url} alt="Gallery match" />
            <div className="text-[10px] text-muted-foreground">Gallery</div>
          </div>
          <div className="min-w-0 flex-1 space-y-1">
            <div className="truncate font-semibold">{d.staff_name || "Unknown person"}</div>
            <div className="text-xs text-muted-foreground">
              {d.camera_name || d.source} · {when(d.created_at)}
            </div>
            <div className="flex flex-wrap gap-1">
              {isCheckin ? (
                <Badge className="bg-sky-600 hover:bg-sky-600">Check-in approval</Badge>
              ) : (
                <OutcomeBadge outcome={d.outcome} />
              )}
              {isCluster ? (
                <Badge variant="outline" className="border-violet-500 text-violet-600">
                  {clusterInfo?.code || "Cluster"} · {clusterInfo?.observations ?? 0} obs · {clusterInfo?.cameras ?? 0}{" "}
                  cam
                </Badge>
              ) : (
                isJourney && (
                  <Badge variant="outline" className="border-violet-500 text-violet-600">
                    Journey{d.track_id != null ? ` · track ${d.track_id}` : ""}
                  </Badge>
                )
              )}
            </div>
            <div className="text-xs">
              Similarity <b>{pct(d.face_similarity)}</b> · Confidence <b>{pct(d.confidence)}</b> · Quality{" "}
              <b>{pct(d.face_quality)}</b>
            </div>
            <div className="line-clamp-2 text-xs text-muted-foreground" title={d.reason}>
              {d.policy?.message || d.reason}
            </div>
            <button type="button" onClick={() => onWhy(d.id)} className="text-xs text-primary underline">
              Why?
            </button>
          </div>
        </div>

        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
          <label className="flex items-center gap-1.5">
            <Checkbox checked={markAttendance} onCheckedChange={(v) => setMarkAttendance(v === true)} />
            Mark attendance
          </label>
          <label className="flex items-center gap-1.5" title={d.can_add_to_gallery ? "" : "No face embedding stored"}>
            <Checkbox
              checked={addToGallery}
              disabled={!d.can_add_to_gallery}
              onCheckedChange={(v) => setAddToGallery(v === true)}
            />
            Add face to gallery (learn)
          </label>
        </div>
        <Input placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} className="h-8" />

        <div className="flex flex-wrap gap-2">
          {d.staff != null && (
            <Button size="sm" disabled={busy} onClick={() => approve.mutate(undefined)}>
              {approve.isPending ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              ) : (
                <Check className="mr-1 h-4 w-4" />
              )}
              Yes, {d.staff_name?.split(" ")[0]}
            </Button>
          )}
          <Button size="sm" variant="outline" disabled={busy} onClick={() => reject.mutate()}>
            <UserX className="mr-1 h-4 w-4" />
            {d.staff != null ? "Not them" : "Dismiss"}
          </Button>
        </div>
        <div className="flex gap-2">
          <Select value={otherStaff} onValueChange={setOtherStaff}>
            <SelectTrigger className="h-8 flex-1 text-xs">
              <SelectValue placeholder="It’s someone else…" />
            </SelectTrigger>
            <SelectContent>
              {employees
                .filter((e) => e.staff_id !== d.staff)
                .map((e) => (
                  <SelectItem key={e.staff_id} value={String(e.staff_id)}>
                    {e.staff_name}
                    {e.employee_id ? ` (${e.employee_id})` : ""}
                  </SelectItem>
                ))}
            </SelectContent>
          </Select>
          <Button
            size="sm"
            variant="secondary"
            disabled={busy || !otherStaff}
            onClick={() => approve.mutate(Number(otherStaff))}
          >
            Assign
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function ReviewQueue({ employees, onWhy }: { employees: IdentityProfile[]; onWhy: OpenById }) {
  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["identity", "decisions", "pending"],
    queryFn: () => identityApi.decisions({ review_status: "pending", limit: 60 }),
    refetchInterval: 15_000,
  })
  const rows = data?.results || []
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Uncertain matches and assisted-mode check-ins. Approving can add the live face to the employee’s gallery so
          recognition improves from your real cameras — no model retraining.
        </p>
        <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
          <RefreshCw className={`mr-1 h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>
      {isLoading ? (
        <div className="flex justify-center py-10">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      ) : rows.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            <ShieldCheck className="mx-auto mb-2 h-8 w-8 text-emerald-600" />
            Nothing waiting for review.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {rows.map((d) => (
            <ReviewCard key={d.id} d={d} employees={employees} onWhy={onWhy} />
          ))}
        </div>
      )}
    </div>
  )
}

// ── employees: mode + gallery ─────────────────────────────────────────────

function GalleryDialog({ staffId, onClose }: { staffId: number | null; onClose: () => void }) {
  const { toast } = useToast()
  const qc = useQueryClient()
  const [showInactive, setShowInactive] = useState(false)
  const { data, isLoading } = useQuery({
    queryKey: ["identity", "staff", staffId, showInactive],
    queryFn: () => identityApi.staff(staffId as number, showInactive),
    enabled: staffId != null,
  })
  const toggle = useMutation({
    mutationFn: async ({ id, active }: { id: number; active: boolean }) => {
      if (active) await identityApi.deactivateEntry(id)
      else await identityApi.reactivateEntry(id)
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["identity"] }),
    onError: (e: Error) =>
      toast({
        title: "Update failed",
        description: e.message,
        variant: "destructive",
      }),
  })
  const entries = useMemo(() => data?.gallery || [], [data])
  const groups = useMemo(() => {
    const byModel = new Map<string, GalleryEntry[]>()
    for (const e of entries) byModel.set(e.model_name, [...(byModel.get(e.model_name) || []), e])
    return [...byModel.entries()]
  }, [entries])

  return (
    <Dialog open={staffId != null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-4xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Face gallery — {data?.profile.staff_name || "…"}</DialogTitle>
          <DialogDescription>
            Each photo is matched individually. Remove photos that are wrong or of poor quality; removed photos stay in
            the audit trail.
          </DialogDescription>
        </DialogHeader>
        <label className="flex items-center gap-2 text-sm">
          <Checkbox checked={showInactive} onCheckedChange={(v) => setShowInactive(v === true)} />
          Show removed photos
        </label>
        {isLoading ? (
          <div className="flex justify-center py-10">
            <Loader2 className="h-6 w-6 animate-spin" />
          </div>
        ) : entries.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            No gallery photos yet. Capture and train this employee in Face Enrollment.
          </p>
        ) : (
          groups.map(([model, list]) => (
            <div key={model} className="space-y-2">
              <div className="text-sm font-medium">
                {MODEL_LABEL[model] || model}{" "}
                <span className="text-muted-foreground">({list.filter((e) => e.is_active).length} active)</span>
              </div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
                {list.map((e) => (
                  <div key={e.id} className={`space-y-1 rounded border p-2 ${e.is_active ? "" : "opacity-50"}`}>
                    <FaceImg url={e.image_url} alt="Gallery face" className="h-32 w-full" />
                    <div className="flex items-center justify-between gap-1">
                      <Badge variant={e.source === "approved_live" ? "default" : "secondary"} className="text-[10px]">
                        {e.source === "approved_live" ? "Live" : "Enrollment"}
                      </Badge>
                      <span className="text-xs" title={e.quality_score == null ? "Not scored by this model" : ""}>
                        Q {pct(e.quality_score)}
                      </span>
                    </div>
                    <div className="truncate text-[10px] text-muted-foreground">
                      {e.source === "approved_live"
                        ? `${e.camera_name || "Camera"} · by ${e.approved_by_name || "—"}`
                        : new Date(e.created_at).toLocaleDateString()}
                    </div>
                    <Button
                      size="sm"
                      variant={e.is_active ? "outline" : "secondary"}
                      className="h-7 w-full text-xs"
                      disabled={toggle.isPending}
                      onClick={() => toggle.mutate({ id: e.id, active: e.is_active })}
                    >
                      {e.is_active ? "Remove" : "Restore"}
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          ))
        )}
      </DialogContent>
    </Dialog>
  )
}

function ReadinessBadge({ p }: { p: IdentityProfile }) {
  const r = p.automatic_readiness
  const tip = Object.entries(r.checks)
    .map(
      ([k, c]) =>
        `${c.ok ? "✓" : "✗"} ${k.replace(/_/g, " ")}: ${c.value}${c.required != null ? ` / ${c.required}` : ` (max ${c.max})`}`
    )
    .join("\n")
  if (p.recognition_mode === "automatic") return <span className="text-xs text-muted-foreground">—</span>
  return r.ready ? (
    <Badge className="bg-emerald-600 hover:bg-emerald-600" title={tip}>
      Ready for automatic
    </Badge>
  ) : (
    <Badge variant="outline" title={tip}>
      Learning
    </Badge>
  )
}

function Employees({
  employees,
  loading,
  onGallery,
}: {
  employees: IdentityProfile[]
  loading: boolean
  onGallery: OpenById
}) {
  const { toast } = useToast()
  const qc = useQueryClient()
  const [search, setSearch] = useState("")
  const setMode = useMutation({
    mutationFn: ({ staffId, mode }: { staffId: number; mode: RecognitionMode }) => identityApi.setMode(staffId, mode),
    onSuccess: (p) => {
      toast({
        title: `${p.staff_name} → ${MODE_LABEL[p.recognition_mode]}`,
        description: MODE_HELP[p.recognition_mode],
      })
      void qc.invalidateQueries({ queryKey: ["identity"] })
    },
    onError: (e: Error) =>
      toast({
        title: "Could not change mode",
        description: e.message,
        variant: "destructive",
      }),
  })
  const rows = useMemo(() => {
    const s = search.trim().toLowerCase()
    return s
      ? employees.filter(
          (e) => e.staff_name.toLowerCase().includes(s) || (e.employee_id || "").toLowerCase().includes(s)
        )
      : employees
  }, [employees, search])

  return (
    <Card>
      <CardHeader className="space-y-3">
        <div>
          <CardTitle className="text-base">Recognition mode per employee</CardTitle>
          <CardDescription>
            Manual → Assisted → Automatic. The system recommends when someone is ready; you make the switch.
          </CardDescription>
        </div>
        <div className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-3">
          {(Object.keys(MODE_LABEL) as RecognitionMode[]).map((m) => (
            <div key={m}>
              <b className="text-foreground">{MODE_LABEL[m]}:</b> {MODE_HELP[m]}
            </div>
          ))}
        </div>
        <Input
          placeholder="Search employee…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-xs"
        />
      </CardHeader>
      <CardContent className="overflow-x-auto">
        {loading ? (
          <div className="flex justify-center py-10">
            <Loader2 className="h-6 w-6 animate-spin" />
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Employee</TableHead>
                <TableHead>Mode</TableHead>
                <TableHead className="text-right">Attendance gallery</TableHead>
                <TableHead className="text-right">Journey gallery</TableHead>
                <TableHead className="text-right">Confirmed / Rejected</TableHead>
                <TableHead className="text-right">Pending</TableHead>
                <TableHead>Readiness</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((p) => (
                <TableRow key={p.staff_id}>
                  <TableCell>
                    <div className="font-medium">{p.staff_name}</div>
                    {p.employee_id && <div className="text-xs text-muted-foreground">{p.employee_id}</div>}
                  </TableCell>
                  <TableCell>
                    <Select
                      value={p.recognition_mode}
                      onValueChange={(v) =>
                        setMode.mutate({
                          staffId: p.staff_id,
                          mode: v as RecognitionMode,
                        })
                      }
                    >
                      <SelectTrigger className="h-8 w-32">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {(Object.keys(MODE_LABEL) as RecognitionMode[]).map((m) => (
                          <SelectItem key={m} value={m}>
                            {MODE_LABEL[m]}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {p.mode_changed_by_name && (
                      <div className="mt-0.5 text-[10px] text-muted-foreground">by {p.mode_changed_by_name}</div>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    {p.gallery_size === 0 ? <span className="text-amber-600">0 (legacy)</span> : p.gallery_size}
                  </TableCell>
                  <TableCell className="text-right">{p.journey_gallery_size}</TableCell>
                  <TableCell className="text-right">
                    {p.confirmed_matches} / {p.rejected_matches}
                  </TableCell>
                  <TableCell className="text-right">{p.pending_reviews || 0}</TableCell>
                  <TableCell>
                    <ReadinessBadge p={p} />
                  </TableCell>
                  <TableCell className="text-right">
                    <Button size="sm" variant="outline" onClick={() => onGallery(p.staff_id)}>
                      <Images className="mr-1 h-4 w-4" />
                      Gallery
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {rows.length === 0 && (
                <TableRow>
                  <TableCell colSpan={8} className="py-8 text-center text-muted-foreground">
                    No enrolled employees.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

// ── audit trail ───────────────────────────────────────────────────────────

const ALL = "all"

function AuditTrail({ employees, onWhy }: { employees: IdentityProfile[]; onWhy: OpenById }) {
  const [filters, setFilters] = useState<DecisionFilters>({
    limit: 50,
    offset: 0,
  })
  const { data, isLoading } = useQuery({
    queryKey: ["identity", "decisions", filters],
    queryFn: () => identityApi.decisions(filters),
  })
  const set = (k: keyof DecisionFilters, v: string) =>
    setFilters((f) => ({
      ...f,
      offset: 0,
      [k]: v === ALL || v === "" ? undefined : k === "staff" ? Number(v) : v,
    }))
  const rows = data?.results || []
  const total = data?.count || 0
  const offset = filters.offset || 0
  const limit = filters.limit || 50

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Identity audit trail</CardTitle>
        <CardDescription>Every accept, review and unknown — with the evidence behind it.</CardDescription>
        <div className="flex flex-wrap gap-2 pt-2">
          <Select value={filters.outcome || ALL} onValueChange={(v) => set("outcome", v)}>
            <SelectTrigger className="h-8 w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All outcomes</SelectItem>
              <SelectItem value="accepted">Accepted</SelectItem>
              <SelectItem value="review">Needs review</SelectItem>
              <SelectItem value="unknown">Unknown</SelectItem>
            </SelectContent>
          </Select>
          <Select value={filters.source || ALL} onValueChange={(v) => set("source", v)}>
            <SelectTrigger className="h-8 w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All sources</SelectItem>
              <SelectItem value="cctv">CCTV</SelectItem>
              <SelectItem value="webcam">Webcam</SelectItem>
              <SelectItem value="journey">Journey</SelectItem>
              <SelectItem value="cluster">Unknown clusters</SelectItem>
            </SelectContent>
          </Select>
          <Select value={filters.staff ? String(filters.staff) : ALL} onValueChange={(v) => set("staff", v)}>
            <SelectTrigger className="h-8 w-48">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All employees</SelectItem>
              {employees.map((e) => (
                <SelectItem key={e.staff_id} value={String(e.staff_id)}>
                  {e.staff_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input
            type="date"
            className="h-8 w-40"
            value={filters.date || ""}
            onChange={(e) => set("date", e.target.value)}
          />
        </div>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        {isLoading ? (
          <div className="flex justify-center py-10">
            <Loader2 className="h-6 w-6 animate-spin" />
          </div>
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Face</TableHead>
                  <TableHead>Time</TableHead>
                  <TableHead>Camera</TableHead>
                  <TableHead>Employee</TableHead>
                  <TableHead>Outcome</TableHead>
                  <TableHead className="text-right">Similarity</TableHead>
                  <TableHead className="text-right">Confidence</TableHead>
                  <TableHead>Attendance</TableHead>
                  <TableHead>Review</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((d) => (
                  <TableRow key={d.id}>
                    <TableCell>
                      <FaceImg url={d.snapshot_url} alt="Face" className="h-12 w-10" />
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs">{when(d.created_at)}</TableCell>
                    <TableCell className="text-xs">{d.camera_name || d.source}</TableCell>
                    <TableCell>{d.staff_name || <span className="text-muted-foreground">—</span>}</TableCell>
                    <TableCell>
                      <OutcomeBadge outcome={d.outcome} />
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">{num(d.face_similarity, 3)}</TableCell>
                    <TableCell className="text-right font-mono text-xs">{num(d.confidence, 3)}</TableCell>
                    <TableCell className="text-xs">
                      {d.attendance_action
                        ? d.attendance_action.replace(/_/g, " ")
                        : d.policy?.action?.replace(/_/g, " ") || "—"}
                    </TableCell>
                    <TableCell>
                      <ReviewBadge status={d.review_status} />
                    </TableCell>
                    <TableCell>
                      <Button size="sm" variant="ghost" onClick={() => onWhy(d.id)}>
                        Why?
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {rows.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={10} className="py-8 text-center text-muted-foreground">
                      No decisions match these filters.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
            {total > limit && (
              <div className="flex items-center justify-end gap-2 pt-3 text-sm">
                <span className="text-muted-foreground">
                  {offset + 1}–{Math.min(offset + limit, total)} of {total}
                </span>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={offset === 0}
                  onClick={() =>
                    setFilters((f) => ({
                      ...f,
                      offset: Math.max(0, offset - limit),
                    }))
                  }
                >
                  Previous
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={offset + limit >= total}
                  onClick={() => setFilters((f) => ({ ...f, offset: offset + limit }))}
                >
                  Next
                </Button>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}

// ── unknown people (clusters) ─────────────────────────────────────────────

function ClusterDialog({ clusterId, onClose }: { clusterId: number | null; onClose: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ["identity", "cluster", clusterId],
    queryFn: () => identityApi.cluster(clusterId as number),
    enabled: clusterId != null,
  })
  return (
    <Dialog open={clusterId != null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-4xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{data?.code || "Unknown person"}</DialogTitle>
          <DialogDescription>
            Journey persons grouped as the same individual, and the observations collected for them.
          </DialogDescription>
        </DialogHeader>
        {isLoading || !data ? (
          <div className="flex justify-center py-10">
            <Loader2 className="h-6 w-6 animate-spin" />
          </div>
        ) : (
          <div className="space-y-5 text-sm">
            <div>
              <div className="mb-2 font-medium">Journey persons ({data.members.length})</div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {data.members.map((m) => (
                  <div key={m.uuid} className="space-y-1 rounded border p-2">
                    <FaceImg url={m.snapshot_url} alt={m.code} className="h-28 w-full" />
                    <div className="font-medium">{m.code}</div>
                    <div className="text-xs text-muted-foreground">
                      {m.observations} obs · {m.latest_camera || "—"}
                    </div>
                    <div className="text-[10px] text-muted-foreground">{when(m.latest_seen_at)}</div>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <div className="mb-2 font-medium">Latest observations</div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Time</TableHead>
                    <TableHead>Camera</TableHead>
                    <TableHead>Track</TableHead>
                    <TableHead>Person</TableHead>
                    <TableHead>Face</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.observations.map((o) => (
                    <TableRow key={o.id}>
                      <TableCell className="whitespace-nowrap text-xs">{when(o.at)}</TableCell>
                      <TableCell className="text-xs">{o.camera || "—"}</TableCell>
                      <TableCell className="text-xs">{o.track_id ?? "—"}</TableCell>
                      <TableCell className="text-xs">{o.person_code}</TableCell>
                      <TableCell className="text-xs">{o.has_face ? "yes" : "body only"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function ClusterCard({
  c,
  employees,
  onOpen,
  onWhy,
}: {
  c: UnknownClusterRow
  employees: IdentityProfile[]
  onOpen: OpenById
  onWhy: OpenById
}) {
  const { toast } = useToast()
  const qc = useQueryClient()
  const [staffId, setStaffId] = useState("")
  const done = () => void qc.invalidateQueries({ queryKey: ["identity"] })
  const assign = useMutation({
    mutationFn: () => identityApi.assignCluster(c.id, Number(staffId)),
    onSuccess: (res) => {
      toast({
        title: `${c.code} identified`,
        description: [
          res.journey?.merged_persons?.length ? `${res.journey.merged_persons.length} journey(s) merged` : null,
          res.journey?.gallery_added ? `${res.journey.gallery_added} face(s) learned` : null,
        ]
          .filter(Boolean)
          .join(" · "),
      })
      done()
    },
    onError: (e: Error) => toast({ title: "Assign failed", description: e.message, variant: "destructive" }),
  })
  const dismiss = useMutation({
    mutationFn: () => identityApi.dismissCluster(c.id),
    onSuccess: () => {
      toast({ title: `${c.code} dismissed`, description: "Won’t be suggested again." })
      done()
    },
    onError: (e: Error) => toast({ title: "Dismiss failed", description: e.message, variant: "destructive" }),
  })
  const busy = assign.isPending || dismiss.isPending
  const cand = c.candidate

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex gap-3">
          <button type="button" onClick={() => onOpen(c.id)} className="shrink-0">
            <FaceImg url={c.thumbnail_url} alt={c.code} />
          </button>
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex items-center gap-2">
              <span className="font-semibold">{c.code}</span>
              {c.status !== "open" && (
                <Badge variant="outline" className="capitalize">
                  {c.status}
                </Badge>
              )}
            </div>
            <div className="text-xs text-muted-foreground">
              {c.person_count} journey person{c.person_count === 1 ? "" : "s"} · {c.observation_count} observations ·{" "}
              {c.camera_ids.length} camera{c.camera_ids.length === 1 ? "" : "s"}
            </div>
            <div className="text-xs text-muted-foreground">
              {when(c.first_seen)} → {when(c.last_seen)}
            </div>
            <div className="truncate text-[10px] text-muted-foreground" title={c.member_codes.join(", ")}>
              {c.member_codes.join(", ")}
            </div>
            {c.staff_name && (
              <div className="text-xs">
                Identified as <b>{c.staff_name}</b>
              </div>
            )}
            {cand && cand.review_status === "pending" && (
              <div className="rounded bg-amber-50 px-2 py-1 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-200">
                Looks like <b>{cand.staff_name}</b> ({pct(cand.face_similarity)}) —{" "}
                <button type="button" className="underline" onClick={() => onWhy(cand.decision_id)}>
                  why?
                </button>{" "}
                · confirm in Review queue
              </div>
            )}
          </div>
        </div>
        {c.status === "open" && (
          <div className="flex gap-2">
            <Select value={staffId} onValueChange={setStaffId}>
              <SelectTrigger className="h-8 flex-1 text-xs">
                <SelectValue placeholder="This is…" />
              </SelectTrigger>
              <SelectContent>
                {employees
                  .filter((e) => !c.rejected_staff_ids.includes(e.staff_id))
                  .map((e) => (
                    <SelectItem key={e.staff_id} value={String(e.staff_id)}>
                      {e.staff_name}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
            <Button size="sm" disabled={busy || !staffId} onClick={() => assign.mutate()}>
              Assign
            </Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => dismiss.mutate()}>
              Dismiss
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function UnknownPeople({ employees, onWhy }: { employees: IdentityProfile[]; onWhy: OpenById }) {
  const { toast } = useToast()
  const qc = useQueryClient()
  const [status, setStatus] = useState<ClusterStatus | "all">("open")
  const [openId, setOpenId] = useState<number | null>(null)
  const { data, isLoading } = useQuery({
    queryKey: ["identity", "clusters", status],
    queryFn: () => identityApi.clusters(status),
    refetchInterval: 60_000,
  })
  const run = useMutation({
    mutationFn: identityApi.runClustering,
    onSuccess: (r) => {
      toast({
        title: "Clustering finished",
        description: `${r.unknown_persons} unknown persons → ${r.clusters} clusters, ${r.candidates_suggested} new candidate(s)`,
      })
      void qc.invalidateQueries({ queryKey: ["identity"] })
    },
    onError: (e: Error) => toast({ title: "Clustering failed", description: e.message, variant: "destructive" }),
  })
  const rows = data?.results || []

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="max-w-3xl text-sm text-muted-foreground">
          Unknown people seen across cameras and days are grouped when their faces match. When a group looks like an
          employee it appears in the Review queue; assigning or approving merges all their journeys into one.
        </p>
        <div className="flex gap-2">
          <Select value={status} onValueChange={(v) => setStatus(v as ClusterStatus | "all")}>
            <SelectTrigger className="h-8 w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="open">Open</SelectItem>
              <SelectItem value="identified">Identified</SelectItem>
              <SelectItem value="dismissed">Dismissed</SelectItem>
              <SelectItem value="all">All</SelectItem>
            </SelectContent>
          </Select>
          <Button size="sm" variant="outline" disabled={run.isPending} onClick={() => run.mutate()}>
            {run.isPending ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Play className="mr-1 h-4 w-4" />}
            Run clustering now
          </Button>
        </div>
      </div>
      {isLoading ? (
        <div className="flex justify-center py-10">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      ) : rows.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            <Users className="mx-auto mb-2 h-8 w-8" />
            No {status === "all" ? "" : status} unknown-person clusters yet. Observations build up as the journey
            pipeline sees unknown people.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {rows.map((c) => (
            <ClusterCard key={c.id} c={c} employees={employees} onOpen={setOpenId} onWhy={onWhy} />
          ))}
        </div>
      )}
      <ClusterDialog clusterId={openId} onClose={() => setOpenId(null)} />
    </div>
  )
}

// ── page ──────────────────────────────────────────────────────────────────

export default function IdentityReviewPage() {
  const [whyId, setWhyId] = useState<number | null>(null)
  const [galleryStaff, setGalleryStaff] = useState<number | null>(null)
  const { data: profiles, isLoading } = useQuery({
    queryKey: ["identity", "profiles"],
    queryFn: identityApi.profiles,
  })
  const { data: pending } = useQuery({
    queryKey: ["identity", "decisions", "pending-count"],
    queryFn: () => identityApi.decisions({ review_status: "pending", limit: 1 }),
    refetchInterval: 15_000,
  })
  const employees = profiles?.results || []
  const pendingTotal = pending?.pending_total ?? 0

  return (
    <ModulePageLayout
      title="Identity Review"
      description="Confirm uncertain matches, grow each employee’s face gallery, and control automatic attendance."
      breadcrumbs={[{ label: "Attendance", href: ROUTES.ATTENDANCE }, { label: "Identity Review" }]}
    >
      <Tabs defaultValue="queue" className="space-y-4">
        <TabsList>
          <TabsTrigger value="queue">
            Review queue
            {pendingTotal > 0 && (
              <Badge className="ml-2 h-5 bg-amber-500 px-1.5 hover:bg-amber-500">{pendingTotal}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="unknown">Unknown people</TabsTrigger>
          <TabsTrigger value="employees">Employees</TabsTrigger>
          <TabsTrigger value="audit">Audit trail</TabsTrigger>
        </TabsList>
        <TabsContent value="queue">
          <ReviewQueue employees={employees} onWhy={setWhyId} />
        </TabsContent>
        <TabsContent value="unknown">
          <UnknownPeople employees={employees} onWhy={setWhyId} />
        </TabsContent>
        <TabsContent value="employees">
          <Employees employees={employees} loading={isLoading} onGallery={setGalleryStaff} />
        </TabsContent>
        <TabsContent value="audit">
          <AuditTrail employees={employees} onWhy={setWhyId} />
        </TabsContent>
      </Tabs>
      <WhyDialog decisionId={whyId} onClose={() => setWhyId(null)} />
      <GalleryDialog staffId={galleryStaff} onClose={() => setGalleryStaff(null)} />
    </ModulePageLayout>
  )
}
