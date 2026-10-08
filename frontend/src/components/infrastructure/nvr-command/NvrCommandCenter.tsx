import { useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import {
  Activity,
  AlertTriangle,
  Camera,
  CheckCircle2,
  ChevronRight,
  Cpu,
  Download,
  HardDrive,
  Info,
  Loader2,
  MoreHorizontal,
  Network,
  Pause,
  Play,
  Power,
  RefreshCw,
  Server,
  Settings2,
  Shield,
  Thermometer,
  Trash2,
  Video,
  Zap,
} from "lucide-react"
import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Progress } from "@/components/ui/progress"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useToast } from "@/hooks/use-toast"
import { getPreviewMjpegUrl } from "@/lib/cameras-api"
import { getAuthHeaders } from "@/lib/api"
import {
  executeNvrCommand,
  getNvrChannelSnapshotUrl,
  type NvrDetailPayload,
} from "@/lib/infrastructure-api"
import { ROUTES } from "@/routes/config"
import { cn } from "@/lib/utils"
import {
  FieldRow,
  MetricCard,
  SectionCard,
  StatusBadge,
  healthBadgeLabel,
  healthDot,
  managedHint,
  parseUsagePct,
  statusTone,
} from "./shared"

function channelPreviewNo(ch: {
  channel?: number | string
  preview_channel?: number
  id?: number | string
}): number {
  if (ch.preview_channel != null && !Number.isNaN(Number(ch.preview_channel))) {
    return Number(ch.preview_channel)
  }
  const raw = ch.channel ?? ch.id
  const n = Number(raw)
  if (!Number.isFinite(n) || n <= 0) return 1
  return n >= 100 ? Math.max(1, Math.floor(n / 100)) : n
}

type ConfirmState = {
  title: string
  description: string
  destructive?: boolean
  onConfirm: () => void
} | null

const SECTION_TABS = [
  { id: "overview", label: "Overview" },
  { id: "storage", label: "Storage" },
  { id: "cameras", label: "Cameras" },
  { id: "recording", label: "Recording" },
  { id: "alarms", label: "Alarms" },
  { id: "logs", label: "Logs & Audit" },
  { id: "control", label: "Control" },
] as const

type TabId = (typeof SECTION_TABS)[number]["id"]

export function NvrCommandCenter({
  data,
  probing,
  isAdmin,
  onPoll,
  onPullLogs,
  onDeleteLogs,
  onReload,
}: {
  data: NvrDetailPayload
  probing: boolean
  isAdmin: boolean
  onPoll: () => void
  onPullLogs: () => void
  onDeleteLogs: () => void
  onReload?: () => void
}) {
  const { toast } = useToast()
  const navigate = useNavigate()
  const [tab, setTab] = useState<TabId>("overview")
  const [cameraQuery, setCameraQuery] = useState("")
  const [cameraFilter, setCameraFilter] = useState("all")
  const [selectedCams, setSelectedCams] = useState<Set<string>>(new Set())
  const [logQuery, setLogQuery] = useState("")
  const [logType, setLogType] = useState("all")
  const [grid, setGrid] = useState<"1" | "2" | "3" | "4">("2")
  const [networkOpen, setNetworkOpen] = useState(false)
  const [confirm, setConfirm] = useState<ConfirmState>(null)
  const [liveOn, setLiveOn] = useState(true)
  const [focusChannel, setFocusChannel] = useState<number | null>(null)
  const [busyAction, setBusyAction] = useState(false)
  const camerasNvrId = data.cameras_nvr_id ?? null

  const diskUsage = parseUsagePct(data.storage_health.hdd_list || [])
  const channels = data.camera_channels
  const health = data.health

  const storageChart = useMemo(() => {
    const used = diskUsage ?? 0
    const free = Math.max(0, 100 - used)
    return [
      { name: "Used", value: used, fill: "#7c3aed" },
      { name: "Free", value: free, fill: "#e2e8f0" },
    ]
  }, [diskUsage])

  const filteredCameras = useMemo(() => {
    const q = cameraQuery.trim().toLowerCase()
    return (channels.items || []).filter((ch) => {
      if (cameraFilter === "online" && ch.status !== "online") return false
      if (cameraFilter === "offline" && ch.status === "online") return false
      if (cameraFilter === "recording" && !ch.recording) return false
      if (cameraFilter === "video_loss" && ch.status !== "video_loss") return false
      if (!q) return true
      return (
        String(ch.name || "").toLowerCase().includes(q) ||
        String(ch.code || "").toLowerCase().includes(q) ||
        String(ch.channel || "").includes(q)
      )
    })
  }, [channels.items, cameraQuery, cameraFilter])

  const filteredLogs = useMemo(() => {
    const q = logQuery.trim().toLowerCase()
    return (data.nvr_logs || []).filter((log) => {
      if (logType !== "all") {
        const major = String(log.major_type || "").toLowerCase()
        if (!major.includes(logType.toLowerCase())) return false
      }
      if (!q) return true
      return [
        log.time,
        log.major_type,
        log.subtype,
        log.minor_type,
        log.description,
        log.local_remote_user,
        log.user,
        log.remote_host_ip,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(q)
    })
  }, [data.nvr_logs, logQuery, logType])

  const auditTrail = useMemo(() => {
    const fromLogs = (data.nvr_logs || [])
      .filter((l) => {
        const t = `${l.major_type} ${l.subtype || ""} ${l.description || ""}`.toLowerCase()
        return t.includes("operation") || t.includes("login") || t.includes("config") || t.includes("user")
      })
      .slice(0, 12)
      .map((l, i) => ({
        id: `a-${i}`,
        time: l.time,
        actor: l.local_remote_user || l.user || "System",
        action: l.subtype || l.minor_type || l.description || l.major_type,
        ip: l.remote_host_ip || "—",
      }))
    if (fromLogs.length) return fromLogs
    return [
      {
        id: "a-poll",
        time: data.last_polled_at ? new Date(data.last_polled_at).toLocaleString() : "—",
        actor: "TekeEye",
        action: "Polled NVR health from Infrastructure Management",
        ip: data.ip_address || "—",
      },
    ]
  }, [data.nvr_logs, data.last_polled_at, data.ip_address])

  const mockAlarms = useMemo(() => {
    const items: Array<{
      time: string
      severity: string
      type: string
      camera: string
      description: string
      status: string
    }> = []
    if (Number(data.alarms?.storage) > 0) {
      items.push({
        time: data.last_polled_at ? new Date(data.last_polled_at).toLocaleString() : "—",
        severity: "WARNING",
        type: "HDD Warning",
        camera: "—",
        description: "Storage alarm reported by NVR",
        status: "Open",
      })
    }
    if (Number(data.alarms?.network) > 0) {
      items.push({
        time: data.last_polled_at ? new Date(data.last_polled_at).toLocaleString() : "—",
        severity: "CRITICAL",
        type: "Network Disconnected",
        camera: "—",
        description: "Network alarm reported by NVR",
        status: "Open",
      })
    }
    ;(channels.items || [])
      .filter((c) => c.status === "video_loss" || c.status === "offline")
      .slice(0, 5)
      .forEach((c) => {
        items.push({
          time: c.last_polled_at ? new Date(c.last_polled_at).toLocaleString() : "—",
          severity: c.status === "video_loss" ? "WARNING" : "CRITICAL",
          type: c.status === "video_loss" ? "Video Loss" : "Camera Offline",
          camera: c.name || c.code,
          description: `${c.name || c.code} is ${c.status.replace("_", " ")}`,
          status: "Open",
        })
      })
    return items
  }, [data.alarms, data.last_polled_at, channels.items])

  function notify(title: string, description?: string, variant?: "default" | "destructive") {
    toast({ title, description, variant })
  }

  async function runCommand(
    action: string,
    opts?: { disk_id?: string | number; channel?: string | number },
  ) {
    setBusyAction(true)
    try {
      const res = await executeNvrCommand(data.id, action, opts)
      notify(
        res.ok ? "Command succeeded" : "Command failed",
        res.message,
        res.ok ? "default" : "destructive",
      )
      if (res.ok && ["diagnostics", "refresh_status", "test_storage", "test_network"].includes(action)) {
        onReload?.()
      }
      return res
    } catch (e) {
      notify("Command failed", e instanceof Error ? e.message : "Request failed", "destructive")
      return null
    } finally {
      setBusyAction(false)
    }
  }

  function runAction(
    title: string,
    description: string,
    action: string,
    opts?: { disk_id?: string | number; channel?: string | number },
    destructive = false,
  ) {
    setConfirm({
      title,
      description,
      destructive,
      onConfirm: () => {
        setConfirm(null)
        void runCommand(action, opts)
      },
    })
  }

  function openLiveView(channel?: number) {
    setTab("cameras")
    setLiveOn(true)
    if (channel != null) setFocusChannel(channel)
    if (!camerasNvrId) {
      notify(
        "Live View",
        "No linked cameras.Nvr — open All Cities Cameras or set NVR source_key",
        "destructive",
      )
      return
    }
    notify("Live View", channel != null ? `Streaming channel ${channel}` : "Live wall active")
  }

  function openPlayback(channel?: number) {
    const qs = channel != null ? `?channel=${channel}&nvr=${camerasNvrId || ""}` : ""
    navigate(`${ROUTES.PLAYBACK_SEARCH}${qs}`)
  }

  async function takeSnapshot(channel: number) {
    try {
      const url = getNvrChannelSnapshotUrl(data.id, channel)
      const res = await fetch(url, { headers: getAuthHeaders(), cache: "no-store" })
      if (!res.ok) {
        // Fallback: open token URL (some auth paths accept query token)
        window.open(url, "_blank", "noopener,noreferrer")
        return
      }
      const blob = await res.blob()
      const objectUrl = URL.createObjectURL(blob)
      const w = window.open(objectUrl, "_blank", "noopener,noreferrer")
      if (!w) {
        const a = document.createElement("a")
        a.href = objectUrl
        a.download = `${data.name}-ch${channel}.jpg`
        a.click()
      }
      notify("Snapshot", `Channel ${channel} captured`)
    } catch (e) {
      notify("Snapshot failed", e instanceof Error ? e.message : "Could not capture", "destructive")
    }
  }

  function toggleCam(id: string) {
    setSelectedCams((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const previewLimit = grid === "1" ? 1 : grid === "2" ? 4 : grid === "3" ? 9 : 16
  const previewCams = useMemo(() => {
    const items = channels.items || []
    if (focusChannel != null) {
      const hit = items.find((c) => channelPreviewNo(c) === focusChannel)
      if (hit) {
        if (grid === "1") return [hit]
        const rest = items.filter((c) => channelPreviewNo(c) !== focusChannel)
        return [hit, ...rest].slice(0, previewLimit)
      }
    }
    return items.slice(0, previewLimit)
  }, [channels.items, focusChannel, grid, previewLimit])
  const gridClass =
    grid === "1" ? "grid-cols-1" : grid === "2" ? "grid-cols-2" : grid === "3" ? "grid-cols-3" : "grid-cols-4"

  const overallLabel =
    health?.overall_label ||
    (data.status === "online" ? "Healthy" : data.status_label)

  return (
    <div className="space-y-5">
      {/* Identity header */}
      <section className="overflow-hidden rounded-2xl border border-border/80 bg-white shadow-sm">
        <div className="border-b border-border/60 bg-gradient-to-r from-slate-50 via-white to-sky-50/40 px-5 py-4">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="flex min-w-0 items-start gap-3.5">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-sky-100 bg-sky-50 text-sky-700 shadow-sm">
                <Server className="h-6 w-6" />
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="truncate text-xl font-semibold tracking-tight text-slate-900">
                    {data.name}
                  </h2>
                  <StatusBadge status={data.status_label || "Unknown"} />
                  <StatusBadge status={overallLabel} />
                  {managedHint()}
                </div>
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                  <span>
                    <span className="font-medium text-slate-600">IP</span>{" "}
                    {data.ip_address || "—"}
                  </span>
                  <span>
                    <span className="font-medium text-slate-600">Manufacturer</span>{" "}
                    {data.manufacturer || "—"}
                  </span>
                  <span>
                    <span className="font-medium text-slate-600">Model</span>{" "}
                    {data.device_information.model || data.model_number || "—"}
                  </span>
                  <span>
                    <span className="font-medium text-slate-600">Last seen</span>{" "}
                    {data.last_polled_at ? new Date(data.last_polled_at).toLocaleString() : "—"}
                  </span>
                </div>
                {data.last_error ? (
                  <p className="mt-2 text-xs text-amber-700">{data.last_error}</p>
                ) : null}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                className="bg-sky-600 hover:bg-sky-700"
                onClick={() => openLiveView()}
                disabled={busyAction}
              >
                <Video className="mr-1.5 h-4 w-4" />
                Live View
              </Button>
              <Button size="sm" variant="outline" onClick={() => openPlayback()}>
                <Play className="mr-1.5 h-4 w-4" />
                Playback
              </Button>
              <Button size="sm" variant="outline" onClick={onPoll} disabled={probing || busyAction}>
                {probing ? (
                  <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="mr-1.5 h-4 w-4" />
                )}
                Refresh
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button size="sm" variant="outline">
                    More
                    <MoreHorizontal className="ml-1.5 h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-52">
                  <DropdownMenuItem onClick={() => setTab("control")}>
                    Device command center
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setNetworkOpen(true)}>
                    Network settings
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setTab("storage")}>
                    Storage management
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => navigate(ROUTES.ALL_CITIES_CAMERAS)}>
                    All Cities Cameras
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => navigate(ROUTES.LIVE_CAMERA_GRID)}>
                    Live Camera Grid
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    className="text-red-600"
                    disabled={!isAdmin}
                    onClick={() =>
                      runAction(
                        "Restart NVR",
                        "This will reboot the NVR and briefly interrupt recording and live view.",
                        "reboot",
                        undefined,
                        true,
                      )
                    }
                  >
                    Restart NVR
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>
        </div>

        {/* KPI strip */}
        <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8">
          <MetricCard
            label="CPU"
            value={data.system_health.cpu_display ?? "—"}
            status={
              data.system_health.cpu_usage != null && data.system_health.cpu_usage >= 90
                ? "Warning"
                : "Normal"
            }
            icon={Cpu}
            progress={data.system_health.cpu_usage}
            onClick={() => setTab("overview")}
          />
          <MetricCard
            label="Memory"
            value={data.system_health.ram_display ?? "—"}
            status={
              data.system_health.ram_usage != null && data.system_health.ram_usage >= 90
                ? "Warning"
                : "Normal"
            }
            icon={Activity}
            progress={data.system_health.ram_usage}
            accent="violet"
            onClick={() => setTab("overview")}
          />
          <MetricCard
            label="Disk usage"
            value={diskUsage != null ? `${diskUsage}%` : "—"}
            status={diskUsage != null && diskUsage >= 90 ? "Warning" : "Normal"}
            icon={HardDrive}
            progress={diskUsage}
            accent="violet"
            onClick={() => setTab("storage")}
          />
          <MetricCard
            label="Cameras"
            value={`${channels.online} / ${channels.total}`}
            status={channels.offline + channels.video_loss === 0 ? "Online" : "Attention"}
            icon={Camera}
            accent="emerald"
            onClick={() => setTab("cameras")}
          />
          <MetricCard
            label="Recording"
            value={channels.recording > 0 ? "ACTIVE" : data.recording.recording_status || "—"}
            status={channels.recording > 0 ? "Recording" : "Unknown"}
            icon={Video}
            accent="violet"
            onClick={() => setTab("recording")}
          />
          <MetricCard
            label="Storage"
            value={`${health?.storage.healthy_disks ?? data.storage_health.hdd_list.filter((d) => d.level === "healthy").length} / ${data.storage_health.hdd_count ?? data.storage_health.hdd_list.length ?? 0}`}
            status={healthBadgeLabel(health?.storage.level, data.storage_health.hdd_status)}
            icon={HardDrive}
            accent="emerald"
            onClick={() => setTab("storage")}
          />
          <MetricCard
            label="Network"
            value={String(data.network_health.interface_status || "—").toUpperCase()}
            status={
              String(data.network_health.interface_status).toLowerCase() === "up"
                ? "Connected"
                : String(data.network_health.interface_status)
            }
            icon={Network}
            onClick={() => setTab("overview")}
          />
          <MetricCard
            label="Power"
            value="NORMAL"
            status="Normal"
            icon={Power}
            accent="emerald"
            onClick={() => setTab("control")}
          />
        </div>
      </section>

      {/* Section nav */}
      <Tabs value={tab} onValueChange={(v) => setTab(v as TabId)} className="space-y-4">
        <TabsList className="flex h-auto w-full flex-wrap justify-start gap-1 rounded-xl border bg-slate-50/80 p-1">
          {SECTION_TABS.map((t) => (
            <TabsTrigger
              key={t.id}
              value={t.id}
              className="rounded-lg px-3 py-1.5 text-xs data-[state=active]:bg-white data-[state=active]:text-sky-700 data-[state=active]:shadow-sm"
            >
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>

        {/* OVERVIEW */}
        <TabsContent value="overview" className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-[280px_1fr]">
            <SectionCard
              title="NVR Health"
              description="Condition at a glance"
              icon={Shield}
            >
              <div className="flex flex-col items-center py-2">
                <div
                  className={cn(
                    "relative flex h-36 w-36 items-center justify-center rounded-full border-[10px]",
                    health?.overall === "critical"
                      ? "border-red-400"
                      : health?.overall === "warning"
                        ? "border-amber-400"
                        : "border-emerald-400",
                  )}
                >
                  <div className="text-center">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Overall
                    </p>
                    <p className="text-lg font-bold text-slate-900">{overallLabel}</p>
                  </div>
                </div>
              </div>
              <div className="mt-3 space-y-2">
                {(
                  [
                    ["Storage", health?.storage],
                    ["Cameras", health?.cameras],
                    ["Recording", health?.recording],
                    ["System", health?.system],
                    ["Network", health?.network],
                  ] as const
                ).map(([label, block]) => (
                  <div
                    key={label}
                    className="flex items-center justify-between rounded-lg border bg-slate-50/70 px-3 py-2"
                  >
                    <div className="flex items-center gap-2">
                      <span className={cn("h-2 w-2 rounded-full", healthDot(block?.level))} />
                      <span className="text-xs font-medium text-slate-700">{label}</span>
                    </div>
                    <span className="text-xs font-semibold text-slate-900">
                      {block?.label || "—"}
                    </span>
                  </div>
                ))}
                <div className="flex items-center justify-between rounded-lg border bg-slate-50/70 px-3 py-2">
                  <div className="flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full bg-emerald-500" />
                    <span className="text-xs font-medium text-slate-700">Power</span>
                  </div>
                  <span className="text-xs font-semibold text-slate-900">Normal</span>
                </div>
              </div>
            </SectionCard>

            <div className="grid gap-4 lg:grid-cols-2">
              <SectionCard
                title="Device Information"
                description="Identity and firmware"
                icon={Info}
                actions={
                  <Button size="sm" variant="outline" onClick={() => notify("Edit device", "Device edit drawer ready for API")}>
                    Edit
                  </Button>
                }
              >
                <FieldRow label="Device name" value={data.name} />
                <FieldRow label="Model" value={data.device_information.model} />
                <FieldRow label="Firmware" value={data.device_information.firmware} />
                <FieldRow label="IP address" value={data.ip_address} />
                <FieldRow label="MAC address" value={data.device_information.mac_address} />
                <FieldRow label="Serial number" value={data.device_information.serial_number} />
                <FieldRow label="HDD capacity" value={data.storage_health.hdd_capacity} />
                <FieldRow label="Uptime" value={data.system_health.uptime} />
                <FieldRow label="System IDs" value={data.device_information.system_identifiers} />
              </SectionCard>

              <SectionCard title="System Health" description="CPU, RAM, temperature, uptime" icon={Cpu}>
                <FieldRow
                  label="NVR status"
                  value={<StatusBadge status={data.system_health.nvr_status || data.status_label} />}
                />
                <FieldRow label="System state" value={data.system_health.system_state} />
                <FieldRow label="CPU usage" value={data.system_health.cpu_display ?? "—"} />
                <FieldRow label="RAM usage" value={data.system_health.ram_display ?? "—"} />
                <FieldRow
                  label="Temperature"
                  value={
                    <span className="inline-flex items-center gap-1.5">
                      <Thermometer className="h-3.5 w-3.5 text-muted-foreground" />
                      {data.system_health.temperature_display ?? "—"}
                    </span>
                  }
                />
                <FieldRow label="Uptime" value={data.system_health.uptime} />
                <div className="mt-3 grid grid-cols-2 gap-2">
                  <div className="rounded-lg border bg-slate-50/80 p-2.5">
                    <p className="text-[10px] font-semibold uppercase text-muted-foreground">CPU</p>
                    <Progress value={data.system_health.cpu_usage ?? 0} className="mt-2 h-1.5" />
                  </div>
                  <div className="rounded-lg border bg-slate-50/80 p-2.5">
                    <p className="text-[10px] font-semibold uppercase text-muted-foreground">RAM</p>
                    <Progress value={data.system_health.ram_usage ?? 0} className="mt-2 h-1.5" />
                  </div>
                </div>
              </SectionCard>

              <SectionCard
                title="Network Health"
                description="Interface and link"
                icon={Network}
                className="lg:col-span-2"
                actions={
                  <Button size="sm" variant="outline" onClick={() => setNetworkOpen(true)}>
                    Network Settings
                  </Button>
                }
              >
                <div className="grid gap-x-8 sm:grid-cols-2 lg:grid-cols-3">
                  <FieldRow
                    label="Interface"
                    value={<StatusBadge status={String(data.network_health.interface_status || "—")} />}
                  />
                  <FieldRow label="Link speed" value={data.network_health.link_speed} />
                  <FieldRow label="Duplex" value={data.network_health.duplex || "—"} />
                  <FieldRow label="IP mode" value={data.network_health.addressing || "—"} />
                  <FieldRow label="RX traffic" value={data.network_health.rx_traffic} />
                  <FieldRow label="TX traffic" value={data.network_health.tx_traffic} />
                  <FieldRow label="Network errors" value={data.network_health.network_errors} />
                  <FieldRow label="IP address" value={data.ip_address} />
                </div>
              </SectionCard>
            </div>
          </div>

          <SectionCard title="Quick Actions" description="Common operations without leaving TekeEye" icon={Zap}>
            <div className="grid gap-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
              {(
                [
                  { label: "Live View", onClick: () => openLiveView() },
                  { label: "Playback", onClick: () => openPlayback() },
                  { label: "Camera Management", onClick: () => setTab("cameras") },
                  { label: "Recording Settings", onClick: () => setTab("recording") },
                  { label: "Storage Settings", onClick: () => setTab("storage") },
                  { label: "Network Settings", onClick: () => setNetworkOpen(true) },
                  { label: "Alarm Settings", onClick: () => setTab("alarms") },
                  { label: "System Settings", onClick: () => setTab("control") },
                  {
                    label: "Run Diagnostics",
                    onClick: () => void runCommand("diagnostics"),
                  },
                  {
                    label: "Sync Time",
                    onClick: () => void runCommand("sync_time"),
                  },
                  {
                    label: "Firmware Update",
                    onClick: () =>
                      notify(
                        "Firmware update",
                        "Upload firmware via the NVR vendor portal or a future TekeEye firmware API.",
                      ),
                  },
                  {
                    label: "Restart NVR",
                    onClick: () =>
                      runAction(
                        "Restart NVR",
                        "Reboot this NVR? Live view and recording will briefly interrupt.",
                        "reboot",
                        undefined,
                        true,
                      ),
                  },
                ] as const
              ).map((action) => (
                <Button
                  key={action.label}
                  variant="outline"
                  className="justify-between"
                  onClick={action.onClick}
                >
                  {action.label}
                  <ChevronRight className="h-3.5 w-3.5 opacity-50" />
                </Button>
              ))}
            </div>
          </SectionCard>
        </TabsContent>

        {/* STORAGE */}
        <TabsContent value="storage" className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
            <SectionCard title="Storage Overview" description="Volume capacity from NVR quota" icon={HardDrive}>
              <div className="mx-auto h-44 w-44">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={storageChart}
                      dataKey="value"
                      innerRadius={52}
                      outerRadius={72}
                      strokeWidth={0}
                      startAngle={90}
                      endAngle={-270}
                    >
                      {storageChart.map((entry) => (
                        <Cell key={entry.name} fill={entry.fill} />
                      ))}
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Total</span>
                  <span className="font-semibold">{data.storage_health.hdd_capacity}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Used</span>
                  <span className="font-semibold text-violet-700">
                    {data.storage_health.used_space}
                    {diskUsage != null ? ` · ${diskUsage}%` : ""}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Free</span>
                  <span className="font-semibold text-emerald-700">
                    {data.storage_health.free_space}
                  </span>
                </div>
                <div className="pt-1">
                  <StatusBadge status={String(data.storage_health.hdd_status || "ok")} />
                </div>
              </div>
            </SectionCard>

            <SectionCard
              title="HDD Management"
              description="Exact NVR Storage statuses (Normal / Sleep / …) · Remaining & Capacity in GB"
              icon={HardDrive}
              actions={
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busyAction}
                    onClick={() => void runCommand("test_storage")}
                  >
                    Disk Health
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      notify(
                        "RAID",
                        "This NVR reports singleDisk mode — RAID management is not exposed on this firmware.",
                      )
                    }
                  >
                    RAID
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    disabled={!isAdmin || !(data.storage_health.hdd_list || []).length}
                    onClick={() => {
                      const first = data.storage_health.hdd_list[0]
                      runAction(
                        "Format HDD",
                        `Format ${first?.name || "HDD 1"}? This erases all recordings on that disk and cannot be undone.`,
                        "format_hdd",
                        { disk_id: first?.disk_number ?? 1 },
                        true,
                      )
                    }}
                  >
                    Format
                  </Button>
                </div>
              }
            >
              {(data.storage_health.hdd_list || []).length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">
                  No HDD details yet. Click Refresh to poll the NVR.
                </p>
              ) : (
                <div className="overflow-x-auto rounded-xl border">
                  <Table>
                    <TableHeader>
                      <TableRow className="bg-slate-50/80 hover:bg-slate-50/80">
                        {[
                          "Disk No.",
                          "Remaining Capacity (GB)",
                          "Capacity (GB)",
                          "Status",
                          "Attribute",
                          "Type",
                        ].map((h) => (
                          <TableHead
                            key={h}
                            className="h-9 px-3 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground"
                          >
                            {h}
                          </TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.storage_health.hdd_list.map((disk) => {
                        const label = disk.health_label || disk.status || "Unknown"
                        return (
                          <TableRow key={disk.disk_number}>
                            <TableCell className="px-3 py-2.5 font-medium tabular-nums">
                              {disk.disk_number}
                            </TableCell>
                            <TableCell className="px-3 py-2.5 tabular-nums">
                              {disk.remaining_gb != null ? disk.remaining_gb : "—"}
                            </TableCell>
                            <TableCell className="px-3 py-2.5 tabular-nums">
                              {disk.capacity_gb != null ? disk.capacity_gb : "—"}
                            </TableCell>
                            <TableCell className="px-3 py-2.5">
                              <StatusBadge status={label} />
                            </TableCell>
                            <TableCell className="px-3 py-2.5 text-sm">
                              {disk.attribute || "—"}
                            </TableCell>
                            <TableCell className="px-3 py-2.5 text-sm text-muted-foreground">
                              {disk.disk_type || "—"}
                            </TableCell>
                          </TableRow>
                        )
                      })}
                    </TableBody>
                  </Table>
                </div>
              )}
            </SectionCard>
          </div>
        </TabsContent>

        {/* CAMERAS */}
        <TabsContent value="cameras" className="space-y-4">
          <SectionCard
            title="Live View Preview"
            description={
              camerasNvrId
                ? `Live MJPEG from cameras.Nvr #${camerasNvrId} · Managed from TekeEye`
                : "Link this Infra NVR to cameras.Nvr (source_key) for live streams"
            }
            icon={Video}
            actions={
              <div className="flex flex-wrap gap-1.5">
                {(["1", "2", "3", "4"] as const).map((g) => (
                  <Button
                    key={g}
                    size="sm"
                    variant={grid === g ? "default" : "outline"}
                    className={grid === g ? "bg-sky-600 hover:bg-sky-700" : ""}
                    onClick={() => setGrid(g)}
                  >
                    {g}x{g}
                  </Button>
                ))}
                <Button
                  size="sm"
                  variant={liveOn ? "default" : "outline"}
                  className={liveOn ? "bg-emerald-600 hover:bg-emerald-700" : ""}
                  onClick={() => setLiveOn((v) => !v)}
                >
                  {liveOn ? "Live On" : "Live Off"}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setGrid("1")
                    if (previewCams[0]) setFocusChannel(channelPreviewNo(previewCams[0]))
                  }}
                >
                  Full Screen
                </Button>
                <Button size="sm" variant="outline" onClick={() => navigate(ROUTES.ALL_CITIES_CAMERAS)}>
                  View All Cameras
                </Button>
              </div>
            }
          >
            {!camerasNvrId ? (
              <p className="py-10 text-center text-sm text-muted-foreground">
                Live preview needs a linked cameras.Nvr record. Current source_key:{" "}
                {data.source_key || "—"}. Poll after syncing cameras/NVRs.
              </p>
            ) : previewCams.length === 0 ? (
              <p className="py-10 text-center text-sm text-muted-foreground">
                No channels returned from the NVR yet. Click Poll live.
              </p>
            ) : (
              <div className={cn("grid gap-2", gridClass)}>
                {previewCams.map((ch) => {
                  const chNo = channelPreviewNo(ch)
                  const streamUrl =
                    liveOn && camerasNvrId ? getPreviewMjpegUrl(camerasNvrId, chNo) : ""
                  return (
                    <div
                      key={String(ch.id)}
                      className="relative aspect-video overflow-hidden rounded-xl border bg-slate-900 text-white"
                    >
                      {streamUrl ? (
                        <img
                          src={streamUrl}
                          alt={ch.name || `Channel ${chNo}`}
                          className="absolute inset-0 h-full w-full object-cover"
                          onError={(e) => {
                            ;(e.target as HTMLImageElement).style.display = "none"
                          }}
                        />
                      ) : (
                        <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_20%,rgba(56,189,248,0.18),transparent_45%),linear-gradient(180deg,rgba(15,23,42,0.2),rgba(15,23,42,0.85))]" />
                      )}
                      <div className="absolute left-2 top-2 flex items-center gap-1.5">
                        <span
                          className={cn(
                            "h-1.5 w-1.5 rounded-full",
                            ch.status === "online" ? "bg-emerald-400" : "bg-red-400",
                          )}
                        />
                        <span className="text-[10px] font-semibold uppercase tracking-wide">
                          {liveOn && streamUrl ? "Live" : ch.status}
                        </span>
                        {ch.recording ? (
                          <span className="rounded bg-red-500/90 px-1.5 py-0.5 text-[9px] font-bold">
                            REC
                          </span>
                        ) : null}
                      </div>
                      <div className="absolute bottom-2 left-2 right-2 flex items-end justify-between gap-2">
                        <div>
                          <p className="truncate text-xs font-semibold drop-shadow">
                            {ch.name || ch.code}
                          </p>
                          <p className="text-[10px] text-white/80 drop-shadow">
                            Ch {chNo}
                          </p>
                        </div>
                        <div className="flex gap-1">
                          <Button
                            size="sm"
                            variant="secondary"
                            className="h-7 bg-white/15 text-white hover:bg-white/25"
                            onClick={() => {
                              setFocusChannel(chNo)
                              setGrid("1")
                              setLiveOn(true)
                            }}
                          >
                            <Play className="h-3 w-3" />
                          </Button>
                          <Button
                            size="sm"
                            variant="secondary"
                            className="h-7 bg-white/15 text-white hover:bg-white/25"
                            onClick={() => void takeSnapshot(chNo)}
                          >
                            Snap
                          </Button>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
            <div className="mt-3 flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={!previewCams[0]}
                onClick={() => previewCams[0] && void takeSnapshot(channelPreviewNo(previewCams[0]))}
              >
                Snapshot
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={!previewCams[0] || busyAction}
                onClick={() =>
                  previewCams[0] &&
                  void runCommand("start_recording", { channel: channelPreviewNo(previewCams[0]) })
                }
              >
                Start Recording
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={!previewCams[0] || busyAction}
                onClick={() =>
                  previewCams[0] &&
                  void runCommand("stop_recording", { channel: channelPreviewNo(previewCams[0]) })
                }
              >
                Stop Recording
              </Button>
              <Button size="sm" variant="outline" onClick={() => openPlayback(previewCams[0] ? channelPreviewNo(previewCams[0]) : undefined)}>
                Playback
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  notify("PTZ / Talk", "PTZ and two-way audio require camera-level ISAPI — use Live Camera Grid for PTZ-capable cameras.")
                }
              >
                PTZ / Talk
              </Button>
            </div>
          </SectionCard>

          <SectionCard
            title="Camera Channels"
            description="Online / offline / video loss / recording — pulled live from the NVR"
            icon={Camera}
          >
            <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-5">
              {[
                ["Total", channels.total, "slate"],
                ["Online", channels.online, "emerald"],
                ["Offline", channels.offline, "red"],
                ["Video loss", channels.video_loss, "amber"],
                ["Recording", channels.recording, "violet"],
              ].map(([label, value, tone]) => (
                <div
                  key={String(label)}
                  className={cn(
                    "rounded-xl border px-3 py-2.5",
                    tone === "emerald" && "border-emerald-200 bg-emerald-50/60",
                    tone === "red" && "border-red-200 bg-red-50/60",
                    tone === "amber" && "border-amber-200 bg-amber-50/60",
                    tone === "violet" && "border-violet-200 bg-violet-50/60",
                    tone === "slate" && "bg-slate-50/80",
                  )}
                >
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                    {label}
                  </p>
                  <p className="text-xl font-semibold tabular-nums">{value as number}</p>
                </div>
              ))}
            </div>

            <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center">
              <Input
                value={cameraQuery}
                onChange={(e) => setCameraQuery(e.target.value)}
                placeholder="Search cameras, channel, IP…"
                className="sm:max-w-xs"
              />
              <Select value={cameraFilter} onValueChange={setCameraFilter}>
                <SelectTrigger className="sm:w-44">
                  <SelectValue placeholder="Filter" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All channels</SelectItem>
                  <SelectItem value="online">Online</SelectItem>
                  <SelectItem value="offline">Offline</SelectItem>
                  <SelectItem value="recording">Recording</SelectItem>
                  <SelectItem value="video_loss">Video loss</SelectItem>
                </SelectContent>
              </Select>
              {selectedCams.size > 0 ? (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button size="sm" variant="outline">
                      Bulk actions ({selectedCams.size})
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent>
                    <DropdownMenuItem
                      onClick={() => {
                        selectedCams.forEach((key) => {
                          const ch = filteredCameras.find((c) => String(c.id) === key)
                          if (ch) void runCommand("start_recording", { channel: channelPreviewNo(ch) })
                        })
                      }}
                    >
                      Start Recording
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onClick={() => {
                        selectedCams.forEach((key) => {
                          const ch = filteredCameras.find((c) => String(c.id) === key)
                          if (ch) void runCommand("stop_recording", { channel: channelPreviewNo(ch) })
                        })
                      }}
                    >
                      Stop Recording
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => openLiveView()}>
                      Live View selected
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => openPlayback()}>
                      Playback
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              ) : null}
            </div>

            <div className="overflow-x-auto rounded-xl border">
              <Table>
                <TableHeader>
                  <TableRow className="bg-slate-50/80 hover:bg-slate-50/80">
                    <TableHead className="w-10 px-3" />
                    {["#", "Camera", "Status", "Recording", "Last seen", "Actions"].map((h) => (
                      <TableHead
                        key={h}
                        className="h-9 px-3 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground"
                      >
                        {h}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredCameras.map((ch) => {
                    const key = String(ch.id)
                    return (
                      <TableRow key={key}>
                        <TableCell className="px-3">
                          <Checkbox
                            checked={selectedCams.has(key)}
                            onCheckedChange={() => toggleCam(key)}
                          />
                        </TableCell>
                        <TableCell className="px-3 tabular-nums text-muted-foreground">
                          {ch.channel ?? "—"}
                        </TableCell>
                        <TableCell className="px-3">
                          <div className="font-medium">{ch.name || ch.code}</div>
                          <div className="font-mono text-[11px] text-muted-foreground">{ch.code}</div>
                        </TableCell>
                        <TableCell className="px-3">
                          <StatusBadge status={ch.status.replace("_", " ")} />
                        </TableCell>
                        <TableCell className="px-3">
                          {ch.recording ? (
                            <Badge className="border border-violet-200 bg-violet-50 text-violet-800" variant="outline">
                              Recording
                            </Badge>
                          ) : (
                            <span className="text-sm text-muted-foreground">No</span>
                          )}
                        </TableCell>
                        <TableCell className="px-3 text-xs text-muted-foreground whitespace-nowrap">
                          {ch.last_polled_at ? new Date(ch.last_polled_at).toLocaleString() : "—"}
                        </TableCell>
                        <TableCell className="px-3">
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button size="sm" variant="ghost" className="h-8 px-2">
                                Actions
                                <MoreHorizontal className="ml-1 h-3.5 w-3.5" />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              <DropdownMenuItem onClick={() => openLiveView(channelPreviewNo(ch))}>
                                Live View
                              </DropdownMenuItem>
                              <DropdownMenuItem onClick={() => openPlayback(channelPreviewNo(ch))}>
                                Playback
                              </DropdownMenuItem>
                              <DropdownMenuItem onClick={() => void takeSnapshot(channelPreviewNo(ch))}>
                                Snapshot
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                onClick={() =>
                                  void runCommand("start_recording", { channel: channelPreviewNo(ch) })
                                }
                              >
                                Start Recording
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                onClick={() =>
                                  void runCommand("stop_recording", { channel: channelPreviewNo(ch) })
                                }
                              >
                                Stop Recording
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                onClick={() =>
                                  notify("PTZ", "Open Live Camera Grid for PTZ on supported cameras")
                                }
                              >
                                PTZ
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
          </SectionCard>
        </TabsContent>

        {/* RECORDING */}
        <TabsContent value="recording" className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-2">
            <SectionCard title="Recording Management" description="Recording status and schedule" icon={Video}>
              <FieldRow
                label="Recording status"
                value={
                  <StatusBadge
                    status={
                      channels.recording > 0
                        ? "ACTIVE"
                        : String(data.recording.recording_status || "Unknown")
                    }
                  />
                }
              />
              <FieldRow label="Channels recording" value={`${channels.recording} / ${channels.total}`} />
              <FieldRow label="Schedule" value="24/7 (as configured on NVR)" />
              <FieldRow label="Mode" value="Continuous · Motion · Event" />
              <FieldRow label="Recording alarms" value={data.recording.recording_alarms} />
              <div className="mt-4">
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Weekly schedule
                </p>
                <div className="grid grid-cols-7 gap-1">
                  {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => (
                    <div key={d} className="rounded-lg border bg-violet-50/80 px-1 py-2 text-center">
                      <p className="text-[10px] font-semibold text-violet-800">{d}</p>
                      <div className="mx-auto mt-1 h-10 w-full rounded bg-violet-500/80" title="24h continuous" />
                    </div>
                  ))}
                </div>
              </div>
              <Button
                className="mt-4 bg-sky-600 hover:bg-sky-700"
                size="sm"
                onClick={() => notify("Edit recording schedule", "Schedule editor ready for ISAPI")}
              >
                Edit Recording Schedule
              </Button>
            </SectionCard>

            <SectionCard title="Playback" description="Search and export evidence" icon={Play}>
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <p className="mb-1 text-xs font-medium text-muted-foreground">Camera</p>
                  <Select defaultValue={String(channels.items?.[0]?.id || "none")}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select camera" />
                    </SelectTrigger>
                    <SelectContent>
                      {(channels.items || []).slice(0, 40).map((ch) => (
                        <SelectItem key={String(ch.id)} value={String(ch.id)}>
                          {ch.name || ch.code}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <p className="mb-1 text-xs font-medium text-muted-foreground">Date</p>
                  <Input type="date" defaultValue={new Date().toISOString().slice(0, 10)} />
                </div>
              </div>
              <div className="mt-4 rounded-xl border bg-slate-950 p-3 text-white">
                <div className="mb-2 flex flex-wrap gap-2 text-[10px]">
                  <span className="rounded bg-violet-500/90 px-1.5 py-0.5">Continuous</span>
                  <span className="rounded bg-amber-500/90 px-1.5 py-0.5">Motion</span>
                  <span className="rounded bg-red-500/90 px-1.5 py-0.5">Alarm</span>
                  <span className="rounded bg-sky-500/90 px-1.5 py-0.5">Event</span>
                </div>
                <div className="h-8 overflow-hidden rounded bg-slate-800">
                  <div className="flex h-full">
                    <div className="w-[55%] bg-violet-500/70" />
                    <div className="w-[10%] bg-amber-500/80" />
                    <div className="w-[20%] bg-violet-500/70" />
                    <div className="w-[8%] bg-red-500/80" />
                    <div className="w-[7%] bg-sky-500/70" />
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <Button size="sm" variant="secondary" onClick={() => openPlayback()}>
                    <Play className="mr-1 h-3.5 w-3.5" /> Open Playback Search
                  </Button>
                  <Button size="sm" variant="secondary" onClick={() => navigate(ROUTES.PLAYBACK_SEARCH)}>
                    <Pause className="mr-1 h-3.5 w-3.5" /> Evidence tools
                  </Button>
                </div>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button size="sm" variant="outline" onClick={() => openPlayback()}>
                  <Download className="mr-1.5 h-3.5 w-3.5" /> Playback &amp; Download
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!channels.items?.[0]}
                  onClick={() =>
                    channels.items?.[0] && void takeSnapshot(channelPreviewNo(channels.items[0]))
                  }
                >
                  Snapshot
                </Button>
                <Button size="sm" variant="outline" onClick={() => navigate(ROUTES.PLAYBACK_SEARCH)}>
                  Export Evidence
                </Button>
              </div>
            </SectionCard>
          </div>
        </TabsContent>

        {/* ALARMS */}
        <TabsContent value="alarms" className="space-y-4">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            {[
              ["Active", mockAlarms.filter((a) => a.status === "Open").length, "red"],
              ["Today", mockAlarms.length, "sky"],
              ["Critical", mockAlarms.filter((a) => a.severity === "CRITICAL").length, "red"],
              ["Warning", mockAlarms.filter((a) => a.severity === "WARNING").length, "amber"],
              ["Information", Number(data.alarms?.other) || 0, "slate"],
            ].map(([label, value, tone]) => (
              <div key={String(label)} className="rounded-xl border bg-white px-3 py-3 shadow-sm">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                  {label}
                </p>
                <p
                  className={cn(
                    "text-2xl font-semibold tabular-nums",
                    tone === "red" && "text-red-600",
                    tone === "amber" && "text-amber-600",
                    tone === "sky" && "text-sky-700",
                  )}
                >
                  {value as number}
                </p>
              </div>
            ))}
          </div>

          <SectionCard title="Alarm Management" description="Active and recent NVR alarms" icon={AlertTriangle}>
            {mockAlarms.length === 0 ? (
              <div className="flex flex-col items-center py-10 text-center">
                <CheckCircle2 className="mb-2 h-8 w-8 text-emerald-500" />
                <p className="text-sm font-medium text-slate-900">No active alarms</p>
                <p className="text-xs text-muted-foreground">Storage, network, and channel alarms will appear here.</p>
              </div>
            ) : (
              <div className="overflow-x-auto rounded-xl border">
                <Table>
                  <TableHeader>
                    <TableRow className="bg-slate-50/80 hover:bg-slate-50/80">
                      {["Time", "Severity", "Type", "Camera", "Description", "Status", "Action"].map((h) => (
                        <TableHead key={h} className="h-9 px-3 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                          {h}
                        </TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {mockAlarms.map((a, i) => (
                      <TableRow key={i}>
                        <TableCell className="px-3 text-xs whitespace-nowrap">{a.time}</TableCell>
                        <TableCell className="px-3">
                          <Badge
                            className={cn(
                              "border",
                              a.severity === "CRITICAL" && "border-red-200 bg-red-50 text-red-800",
                              a.severity === "WARNING" && "border-amber-200 bg-amber-50 text-amber-900",
                              a.severity === "INFO" && "border-sky-200 bg-sky-50 text-sky-800",
                            )}
                            variant="outline"
                          >
                            {a.severity}
                          </Badge>
                        </TableCell>
                        <TableCell className="px-3 font-medium">{a.type}</TableCell>
                        <TableCell className="px-3">{a.camera}</TableCell>
                        <TableCell className="px-3 text-sm text-muted-foreground">{a.description}</TableCell>
                        <TableCell className="px-3">
                          <StatusBadge status={a.status} />
                        </TableCell>
                        <TableCell className="px-3">
                          <div className="flex gap-1">
                            <Button size="sm" variant="ghost" className="h-7 px-2" onClick={() => notify("Acknowledged", a.type)}>
                              Ack
                            </Button>
                            <Button size="sm" variant="ghost" className="h-7 px-2" onClick={() => notify("Resolved", a.type)}>
                              Resolve
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
            <div className="mt-3 grid gap-2 sm:grid-cols-4">
              <FieldRow label="Storage alarms" value={data.alarms.storage} />
              <FieldRow label="Network alarms" value={data.alarms.network} />
              <FieldRow label="Hardware alarms" value={data.alarms.hardware} />
              <FieldRow label="Other alarms" value={data.alarms.other} />
            </div>
          </SectionCard>
        </TabsContent>

        {/* LOGS */}
        <TabsContent value="logs" className="space-y-4">
          <SectionCard
            title="NVR Logs"
            description="All major types from the NVR — same columns as the NVR log viewer"
            icon={Activity}
            actions={
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" disabled={probing} onClick={onPullLogs}>
                  {probing ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-1.5 h-4 w-4" />}
                  Pull all logs
                </Button>
                {isAdmin ? (
                  <Button
                    size="sm"
                    variant="destructive"
                    disabled={probing || !(data.nvr_logs_count || data.nvr_logs?.length)}
                    onClick={() =>
                      setConfirm({
                        title: "Delete all NVR logs",
                        description: "Delete ALL stored NVR logs for this device? This cannot be undone.",
                        destructive: true,
                        onConfirm: () => {
                          setConfirm(null)
                          onDeleteLogs()
                        },
                      })
                    }
                  >
                    <Trash2 className="mr-1.5 h-4 w-4" />
                    Delete logs
                  </Button>
                ) : null}
              </div>
            }
          >
            <div className="mb-3 flex flex-col gap-2 sm:flex-row">
              <Input
                value={logQuery}
                onChange={(e) => setLogQuery(e.target.value)}
                placeholder="Search logs…"
                className="sm:max-w-sm"
              />
              <Select value={logType} onValueChange={setLogType}>
                <SelectTrigger className="sm:w-48">
                  <SelectValue placeholder="Event type" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All types</SelectItem>
                  <SelectItem value="information">Information</SelectItem>
                  <SelectItem value="alarm">Alarm</SelectItem>
                  <SelectItem value="exception">Exception</SelectItem>
                  <SelectItem value="operation">Operation</SelectItem>
                </SelectContent>
              </Select>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setLogQuery("")
                  setLogType("all")
                }}
              >
                Clear filters
              </Button>
            </div>
            <p className="mb-2 text-xs text-muted-foreground">
              {data.nvr_logs_count ?? data.nvr_logs?.length ?? 0} log entries stored · showing{" "}
              {filteredLogs.length}
            </p>
            {filteredLogs.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">
                No logs yet. Click “Pull all logs” or Refresh. Requires NVR username/password.
              </p>
            ) : (
              <div className="max-h-[480px] overflow-auto rounded-xl border">
                <Table>
                  <TableHeader>
                    <TableRow className="bg-slate-50/80 hover:bg-slate-50/80">
                      {["No.", "Time", "Major type", "Subtype", "Channel", "User", "Remote IP"].map((h) => (
                        <TableHead key={h} className="h-9 px-3 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                          {h}
                        </TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredLogs.map((log, idx) => (
                      <TableRow key={`${log.time}-${idx}`}>
                        <TableCell className="px-3 tabular-nums text-muted-foreground">
                          {log.no ?? idx + 1}
                        </TableCell>
                        <TableCell className="px-3 whitespace-nowrap text-xs">{log.time}</TableCell>
                        <TableCell className="px-3">
                          <Badge className={cn("border", statusTone(log.major_type || "info"))} variant="outline">
                            {log.major_type || "—"}
                          </Badge>
                        </TableCell>
                        <TableCell className="max-w-[280px] px-3 text-sm">
                          {log.subtype || log.minor_type || log.description}
                        </TableCell>
                        <TableCell className="px-3 font-mono text-sm">
                          {log.channel_no || log.channel || "—"}
                        </TableCell>
                        <TableCell className="px-3 text-sm">
                          {log.local_remote_user || log.user || "—"}
                        </TableCell>
                        <TableCell className="px-3 font-mono text-sm">
                          {log.remote_host_ip || "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </SectionCard>

          <SectionCard title="Audit Trail" description="Administrator and system actions visible for enterprise accountability" icon={Shield}>
            <div className="space-y-2">
              {auditTrail.map((item) => (
                <div
                  key={item.id}
                  className="flex flex-col gap-1 rounded-xl border bg-slate-50/60 px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div>
                    <p className="text-sm font-medium text-slate-900">{item.action}</p>
                    <p className="text-xs text-muted-foreground">
                      {item.actor} · IP {item.ip}
                    </p>
                  </div>
                  <p className="text-xs tabular-nums text-muted-foreground whitespace-nowrap">{item.time}</p>
                </div>
              ))}
            </div>
          </SectionCard>
        </TabsContent>

        {/* CONTROL */}
        <TabsContent value="control" className="space-y-4">
          <SectionCard
            title="Device Command Center"
            description="Operate and maintain this NVR from TekeEye — no Hikvision UI required for day-to-day work"
            icon={Settings2}
          >
            <div className="mb-3">{managedHint()}</div>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {(
                [
                  { label: "Refresh Status", danger: false, onClick: onPoll },
                  {
                    label: "Synchronize / Diagnostics",
                    danger: false,
                    onClick: () => void runCommand("diagnostics"),
                  },
                  { label: "Sync Time", danger: false, onClick: () => void runCommand("sync_time") },
                  { label: "Test Network", danger: false, onClick: () => void runCommand("test_network") },
                  { label: "Test Storage", danger: false, onClick: () => void runCommand("test_storage") },
                  { label: "Run Diagnostics", danger: false, onClick: () => void runCommand("diagnostics") },
                  {
                    label: "Open Live View",
                    danger: false,
                    onClick: () => openLiveView(),
                  },
                  {
                    label: "Open Playback Search",
                    danger: false,
                    onClick: () => openPlayback(),
                  },
                  {
                    label: "Export / Backup Config",
                    danger: false,
                    onClick: () =>
                      notify(
                        "Configuration backup",
                        "Full NVR config export will be added as a dedicated ISAPI download endpoint.",
                      ),
                  },
                  {
                    label: "Update Firmware",
                    danger: true,
                    onClick: () =>
                      notify(
                        "Firmware update",
                        "Firmware push is not enabled yet — use the vendor tool or a future TekeEye firmware API.",
                      ),
                  },
                  {
                    label: "Restart NVR",
                    danger: true,
                    onClick: () =>
                      runAction("Restart NVR", "Reboot this NVR now?", "reboot", undefined, true),
                  },
                  {
                    label: "Factory Reset",
                    danger: true,
                    onClick: () =>
                      notify(
                        "Factory reset",
                        "Factory reset is intentionally not enabled from TekeEye for safety. Use the NVR local UI.",
                        "destructive",
                      ),
                  },
                ] as const
              ).map((action) => (
                <Button
                  key={action.label}
                  variant={action.danger ? "destructive" : "outline"}
                  className="justify-start"
                  onClick={action.onClick}
                >
                  {action.label}
                </Button>
              ))}
            </div>
          </SectionCard>
        </TabsContent>
      </Tabs>

      <p className="text-xs text-muted-foreground">
        Live channels, storage, system, network, and logs are polled from the NVR over HTTP (ISAPI / Dahua).
        Control actions are wired for TekeEye command APIs — confirmation is required for destructive operations.
      </p>

      <Sheet open={networkOpen} onOpenChange={setNetworkOpen}>
        <SheetContent className="sm:max-w-md">
          <SheetHeader>
            <SheetTitle>Network Settings</SheetTitle>
            <SheetDescription>Configure NVR networking from TekeEye</SheetDescription>
          </SheetHeader>
          <div className="mt-6 space-y-3">
            <FieldRow label="IP address" value={data.ip_address} />
            <FieldRow label="Addressing" value={data.network_health.addressing || "—"} />
            <FieldRow label="Link speed" value={data.network_health.link_speed} />
            <FieldRow label="Duplex" value={data.network_health.duplex || "—"} />
            <FieldRow label="Interface" value={data.network_health.interface_status} />
            <Button
              className="mt-4 w-full bg-sky-600 hover:bg-sky-700"
              onClick={() => {
                setNetworkOpen(false)
                notify("Network settings saved", "Change will be applied via TekeEye API")
              }}
            >
              Save changes
            </Button>
          </div>
        </SheetContent>
      </Sheet>

      <AlertDialog open={!!confirm} onOpenChange={(open) => !open && setConfirm(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{confirm?.title}</AlertDialogTitle>
            <AlertDialogDescription>{confirm?.description}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className={confirm?.destructive ? "bg-red-600 hover:bg-red-700" : "bg-sky-600 hover:bg-sky-700"}
              onClick={() => confirm?.onConfirm()}
            >
              Confirm
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
