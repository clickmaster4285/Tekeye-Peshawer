import { useCallback, useEffect, useMemo, useState } from "react"
import ReactSelect, { type SingleValue } from "react-select"
import { Check, Loader2, RefreshCw, X } from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { useToast } from "@/hooks/use-toast"
import { resolveMediaUrl } from "@/lib/cameras-api"
import { recognitionApi, type FaceSample } from "@/lib/recognition-api"
import type { StaffOption } from "./FaceEnrollment"

/**
 * CCTV faces held for HR review. Approving adds the crop to that person's gallery
 * (better matching on real camera angles); every decision is also labelled data for
 * `manage.py calibrate_attendance_threshold`.
 */
export function FaceSampleReview({ staffOptions }: { staffOptions: StaffOption[] }) {
  const { toast } = useToast()
  const [samples, setSamples] = useState<FaceSample[]>([])
  const [pendingCount, setPendingCount] = useState(0)
  const [loading, setLoading] = useState(false)
  const [busyId, setBusyId] = useState<number | null>(null)
  // Reviewer's choice of person per sample; defaults to the system's suggestion.
  const [chosen, setChosen] = useState<Record<number, string>>({})

  const optionByValue = useMemo(() => new Map(staffOptions.map((opt) => [opt.value, opt])), [staffOptions])
  const menuPortalTarget = typeof document !== "undefined" ? document.body : null

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await recognitionApi.faceSamples("pending")
      setSamples(data.results)
      setPendingCount(data.pending_count)
    } catch (err) {
      toast({ title: "Could not load CCTV samples", description: String(err), variant: "destructive" })
    } finally {
      setLoading(false)
    }
  }, [toast])

  useEffect(() => {
    load()
  }, [load])

  const review = async (sample: FaceSample, action: "approve" | "reject") => {
    const staffValue = chosen[sample.id] ?? (sample.suggested_staff_id ? String(sample.suggested_staff_id) : "")
    if (action === "approve" && !staffValue) {
      toast({ title: "Choose who this is first", variant: "destructive" })
      return
    }
    setBusyId(sample.id)
    try {
      await recognitionApi.reviewFaceSample(sample.id, action, action === "approve" ? Number(staffValue) : undefined)
      setSamples((prev) => prev.filter((s) => s.id !== sample.id))
      setPendingCount((n) => Math.max(0, n - 1))
    } catch (err) {
      toast({ title: "Review failed", description: String(err), variant: "destructive" })
    } finally {
      setBusyId(null)
    }
  }

  return (
    <Card className="mt-4">
      <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
        <div className="space-y-1.5">
          <CardTitle>CCTV faces to review {pendingCount > 0 && <Badge variant="secondary">{pendingCount}</Badge>}</CardTitle>
          <CardDescription>
            Confirm who each camera face belongs to. Approved faces teach the system real camera angles;
            reject faces that are not the suggested person.
          </CardDescription>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          <span className="ml-2">Refresh</span>
        </Button>
      </CardHeader>
      <CardContent>
        {samples.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {loading ? "Loading…" : "Nothing to review. Samples appear after CCTV punches and near-misses."}
          </p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {samples.map((sample) => {
              const value = chosen[sample.id] ?? (sample.suggested_staff_id ? String(sample.suggested_staff_id) : "")
              const isBusy = busyId === sample.id
              return (
                <div key={sample.id} className="rounded-lg border overflow-hidden">
                  <img
                    src={resolveMediaUrl(sample.image_url)}
                    alt="CCTV face"
                    className="aspect-square w-full bg-muted object-cover"
                    loading="lazy"
                  />
                  <div className="space-y-2 p-3 text-sm">
                    <div className="flex items-center justify-between gap-2">
                      <Badge variant={sample.kind === "punch" ? "default" : "outline"}>
                        {sample.kind === "punch" ? "Punched" : "Not matched"}
                      </Badge>
                      <span className="text-xs text-muted-foreground">
                        {(sample.confidence * 100).toFixed(0)}% · {sample.camera_name || "Camera"}
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      {sample.suggested_staff_name ? `Looks like ${sample.suggested_staff_name}` : "No suggestion"} ·{" "}
                      {new Date(sample.created_at).toLocaleString()}
                    </p>
                    <ReactSelect<StaffOption, false>
                      options={staffOptions}
                      value={optionByValue.get(value) ?? null}
                      onChange={(opt: SingleValue<StaffOption>) =>
                        setChosen((prev) => ({ ...prev, [sample.id]: opt?.value ?? "" }))
                      }
                      placeholder="Who is this?"
                      isClearable
                      menuPortalTarget={menuPortalTarget ?? undefined}
                      menuPosition={menuPortalTarget ? "fixed" : "absolute"}
                      styles={{ menuPortal: (base) => ({ ...base, zIndex: 60 }) }}
                    />
                    <div className="flex gap-2">
                      <Button size="sm" className="flex-1" onClick={() => review(sample, "approve")} disabled={isBusy}>
                        {isBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                        <span className="ml-1">Approve</span>
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="flex-1"
                        onClick={() => review(sample, "reject")}
                        disabled={isBusy}
                      >
                        <X className="h-4 w-4" />
                        <span className="ml-1">Not them</span>
                      </Button>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
