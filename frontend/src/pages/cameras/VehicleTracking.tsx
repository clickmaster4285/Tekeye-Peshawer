import { useEffect, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Car, ChevronLeft, ChevronRight, FileText, RefreshCw, Search, Settings2 } from "lucide-react"
import { ModulePageLayout } from "@/components/dashboard/module-page-layout"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  fetchPlateCaptures,
  resolveMediaUrl,
  type PlateCapture,
} from "@/lib/cameras-api"

const PAGE_SIZE = 25

function formatTime(value: string) {
  if (!value) return "—"
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleString()
}

function PlateThumb({
  src,
  alt,
  onClick,
}: {
  src: string
  alt: string
  onClick?: () => void
}) {
  const url = resolveMediaUrl(src)
  if (!url) {
    return <div className="h-14 w-24 rounded bg-muted" />
  }
  return (
    <button
      type="button"
      onClick={onClick}
      className="block overflow-hidden rounded border bg-muted/40 transition hover:opacity-90"
    >
      <img src={url} alt={alt} className="h-14 w-24 object-cover" loading="lazy" />
    </button>
  )
}

export default function VehicleTrackingPage() {
  const [q, setQ] = useState("")
  const [debouncedQ, setDebouncedQ] = useState("")
  const [page, setPage] = useState(1)
  const [preview, setPreview] = useState<PlateCapture | null>(null)

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedQ(q.trim()), 300)
    return () => window.clearTimeout(t)
  }, [q])

  useEffect(() => {
    setPage(1)
  }, [debouncedQ])

  const { data, isLoading, isFetching, refetch, error } = useQuery({
    queryKey: ["plate-captures", page, PAGE_SIZE, debouncedQ],
    queryFn: () =>
      fetchPlateCaptures({
        page,
        page_size: PAGE_SIZE,
        q: debouncedQ || undefined,
        cleanup: true,
      }),
    refetchInterval: 8_000,
    placeholderData: (prev) => prev,
  })

  const summary = data?.summary
  const results = data?.results ?? []
  const total = data?.count ?? 0
  const totalPages = data?.total_pages ?? 1
  const cleanup = data?.cleanup

  return (
    <ModulePageLayout
      title="Vehicle Tracking"
      description="Unique ANPR plate reads with crop and scene images. Duplicates are removed automatically."
      breadcrumbs={[{ label: "AI Computer Vision" }, { label: "Vehicle Tracking" }]}
    >
      <div className="grid gap-6">
        <div className="grid gap-4 md:grid-cols-3">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">ANPR Cameras</CardTitle>
              <Car className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{summary?.anpr_cameras ?? "—"}</div>
              <p className="mt-1 text-xs text-muted-foreground">Active</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">Unique plates</CardTitle>
              <FileText className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{summary?.total_captures ?? "—"}</div>
              <p className="mt-1 text-xs text-muted-foreground">
                {summary?.reads_today ?? 0} today · {summary?.unique_plates_today ?? 0} unique today
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">Match Rate</CardTitle>
              <Settings2 className="h-4 w-4 text-green-600" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {summary ? `${summary.match_rate}%` : "—"}
              </div>
              <p className="mt-1 text-xs text-muted-foreground">Valid plates kept after dedupe</p>
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <CardTitle>Plate Captures</CardTitle>
              <CardDescription>
                One row per plate number (best OCR). Duplicate numbers and images are removed.
                {cleanup && (cleanup.removed_rows > 0 || cleanup.deleted_files > 0)
                  ? ` Cleaned ${cleanup.removed_rows} rows · ${cleanup.deleted_files} files.`
                  : ""}{" "}
                Showing {results.length} of {total}
              </CardDescription>
            </div>
            <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:items-center">
              <div className="relative min-w-[220px] flex-1">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  className="pl-8"
                  placeholder="Search plate or camera…"
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                />
              </div>
              <Button
                variant="outline"
                onClick={() => refetch()}
                disabled={isFetching}
                className="gap-2"
              >
                <RefreshCw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
                Refresh
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {error ? (
              <p className="text-sm text-destructive">
                {error instanceof Error ? error.message : "Failed to load plate captures."}
              </p>
            ) : null}
            {isLoading ? (
              <p className="text-sm text-muted-foreground">Loading captures…</p>
            ) : results.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No unique plate captures yet. Run an ANPR camera stream so plates are saved under media.
              </p>
            ) : (
              <>
                <div className="w-full max-w-full overflow-x-auto rounded-lg border">
                  <Table className="min-w-[980px]">
                    <TableHeader>
                      <TableRow>
                        <TableHead>Plate crop</TableHead>
                        <TableHead>Scene</TableHead>
                        <TableHead>Plate number</TableHead>
                        <TableHead>Camera</TableHead>
                        <TableHead>Det / OCR</TableHead>
                        <TableHead>Time</TableHead>
                        <TableHead>Status</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {results.map((row) => (
                        <TableRow key={`${row.plate_number}-${row.camera_key}-${row.timestamp}`}>
                          <TableCell>
                            <PlateThumb
                              src={row.plate_image}
                              alt={row.plate_number || "plate"}
                              onClick={() => setPreview(row)}
                            />
                          </TableCell>
                          <TableCell>
                            <PlateThumb
                              src={row.frame_image}
                              alt="scene"
                              onClick={() => setPreview(row)}
                            />
                          </TableCell>
                          <TableCell className="font-semibold tracking-wide">
                            {row.plate_number || "—"}
                          </TableCell>
                          <TableCell>{row.camera_key || "—"}</TableCell>
                          <TableCell className="text-sm text-muted-foreground">
                            {(row.det_conf * 100).toFixed(0)}% / {(row.ocr_conf * 100).toFixed(0)}%
                          </TableCell>
                          <TableCell className="text-sm">{formatTime(row.timestamp)}</TableCell>
                          <TableCell>
                            <Badge variant={row.accepted ? "default" : "secondary"}>
                              {row.accepted ? "Accepted" : "Low OCR"}
                            </Badge>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
                <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <p className="text-sm text-muted-foreground">
                    Page {page} of {totalPages}
                  </p>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={page <= 1 || isFetching}
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                      className="gap-1"
                    >
                      <ChevronLeft className="h-4 w-4" />
                      Previous
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={page >= totalPages || isFetching}
                      onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                      className="gap-1"
                    >
                      Next
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      <Dialog open={!!preview} onOpenChange={(open) => !open && setPreview(null)}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>
              {preview?.plate_number || "Plate"} · {preview?.camera_key}
            </DialogTitle>
          </DialogHeader>
          {preview ? (
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <p className="mb-2 text-xs text-muted-foreground">Plate crop</p>
                <img
                  src={resolveMediaUrl(preview.plate_image)}
                  alt="plate"
                  className="max-h-64 w-full rounded border object-contain bg-black"
                />
              </div>
              <div>
                <p className="mb-2 text-xs text-muted-foreground">Full frame</p>
                <img
                  src={resolveMediaUrl(preview.frame_image)}
                  alt="frame"
                  className="max-h-64 w-full rounded border object-contain bg-black"
                />
              </div>
              <p className="text-sm text-muted-foreground sm:col-span-2">
                {formatTime(preview.timestamp)} · det {(preview.det_conf * 100).toFixed(0)}% · ocr{" "}
                {(preview.ocr_conf * 100).toFixed(0)}%
              </p>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </ModulePageLayout>
  )
}
