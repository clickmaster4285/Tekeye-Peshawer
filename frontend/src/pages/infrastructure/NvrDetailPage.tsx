import { useCallback, useEffect, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { AlertCircle, Loader2, RefreshCw } from "lucide-react"
import { NvrCommandCenter } from "@/components/infrastructure/nvr-command/NvrCommandCenter"
import { ModulePageLayout } from "@/components/dashboard/module-page-layout"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ROUTES } from "@/routes/config"
import {
  fetchNvrDetail,
  deleteNvrLogs,
  refreshNvrLogs,
  type NvrDetailPayload,
} from "@/lib/infrastructure-api"
import { getStoredUser } from "@/lib/auth"
import { normalizeRole } from "@/lib/role-access"
import { useToast } from "@/hooks/use-toast"

export default function NvrDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { toast } = useToast()
  const nvrId = Number(id)
  const isAdmin = normalizeRole(getStoredUser()?.role) === "ADMIN"
  const [data, setData] = useState<NvrDetailPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [probing, setProbing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(
    async (refresh = false) => {
      if (!Number.isFinite(nvrId)) {
        setError("Invalid NVR id")
        setLoading(false)
        return
      }
      if (refresh) setProbing(true)
      else setLoading(true)
      setError(null)
      try {
        const payload = await fetchNvrDetail(nvrId, { refresh })
        setData(payload)
        if (refresh) {
          toast({ title: "NVR polled", description: "Live health refreshed from the appliance" })
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load NVR detail")
      } finally {
        setLoading(false)
        setProbing(false)
      }
    },
    [nvrId, toast],
  )

  useEffect(() => {
    void load(false)
    const t = window.setInterval(() => void load(false), 30000)
    return () => window.clearInterval(t)
  }, [load])

  if (!Number.isFinite(nvrId)) {
    return (
      <ModulePageLayout title="NVR Detail" description="Invalid NVR" breadcrumbs={[]}>
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>Invalid NVR id.</AlertDescription>
        </Alert>
      </ModulePageLayout>
    )
  }

  return (
    <ModulePageLayout
      title={data?.name || "NVR Command Center"}
      description="Monitor, control, configure, troubleshoot, and audit this NVR from TekeEye."
      breadcrumbs={[
        { label: "Infrastructure Monitoring", href: ROUTES.INFRASTRUCTURE_OVERVIEW },
        { label: "NVR Management", href: ROUTES.INFRASTRUCTURE_NVRS },
        { label: "NVR List", href: ROUTES.INFRASTRUCTURE_NVRS },
        { label: data?.name || `NVR #${nvrId}` },
      ]}
      actions={
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={() => navigate(ROUTES.INFRASTRUCTURE_NVRS)}>
            Back to NVR List
          </Button>
          <Button size="sm" className="bg-sky-600 hover:bg-sky-700" onClick={() => void load(true)} disabled={probing || loading}>
            {probing ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="mr-1.5 h-4 w-4" />
            )}
            Poll live
          </Button>
        </div>
      }
    >
      {error ? (
        <Alert variant="destructive" className="mb-4">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {loading && !data ? (
        <div className="space-y-4">
          <Skeleton className="h-40 w-full rounded-2xl" />
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-28 rounded-xl" />
            ))}
          </div>
          <Skeleton className="h-64 w-full rounded-xl" />
        </div>
      ) : data ? (
        <NvrCommandCenter
          data={data}
          probing={probing}
          isAdmin={isAdmin}
          onPoll={() => void load(true)}
          onReload={() => void load(false)}
          onPullLogs={() =>
            void (async () => {
              setProbing(true)
              setError(null)
              try {
                const res = await refreshNvrLogs(nvrId)
                setData((prev) =>
                  prev
                    ? {
                        ...prev,
                        nvr_logs: res.results,
                        nvr_logs_count: res.count,
                      }
                    : prev,
                )
                toast({ title: "Logs pulled", description: `${res.count} entries stored` })
              } catch (e) {
                setError(e instanceof Error ? e.message : "Failed to pull NVR logs")
              } finally {
                setProbing(false)
              }
            })()
          }
          onDeleteLogs={() =>
            void (async () => {
              setProbing(true)
              setError(null)
              try {
                await deleteNvrLogs(nvrId)
                setData((prev) => (prev ? { ...prev, nvr_logs: [], nvr_logs_count: 0 } : prev))
                toast({ title: "Logs deleted" })
              } catch (e) {
                setError(e instanceof Error ? e.message : "Failed to delete NVR logs")
              } finally {
                setProbing(false)
              }
            })()
          }
        />
      ) : null}
    </ModulePageLayout>
  )
}
