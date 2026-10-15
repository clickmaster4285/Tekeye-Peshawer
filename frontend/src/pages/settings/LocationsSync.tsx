import { useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  History,
  KeyRound,
  Loader2,
  MoreHorizontal,
  Pause,
  Pencil,
  Play,
  Plug,
  Plus,
  Server,
  Trash2,
  XCircle,
} from "lucide-react"
import { ModulePageLayout } from "@/components/dashboard/module-page-layout"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { toast } from "@/components/ui/use-toast"
import { getStoredUser } from "@/lib/auth"
import { normalizeRole } from "@/lib/role-access"
import {
  addSyncSite,
  fetchSyncSites,
  removeSyncSite,
  requestFullHistory,
  rotateSyncSiteKey,
  testSyncSite,
  updateSyncSite,
  type SyncSite,
  type SyncSiteState,
} from "@/lib/sync-sites-api"

const NEW_LOCATION = "__new__"
const QUERY_KEY = ["sync-sites"]

const STATE_STYLE: Record<SyncSiteState, { label: string; className: string }> = {
  ONLINE: { label: "Online", className: "bg-emerald-600 text-white hover:bg-emerald-600" },
  DEGRADED: { label: "Delayed", className: "bg-amber-500 text-white hover:bg-amber-500" },
  OFFLINE: { label: "Offline", className: "bg-red-600 text-white hover:bg-red-600" },
  LONG_OFFLINE: { label: "Offline (30m+)", className: "bg-red-700 text-white hover:bg-red-700" },
  PAUSED: { label: "Paused", className: "bg-slate-500 text-white hover:bg-slate-500" },
  UNKNOWN: { label: "Not connected yet", className: "bg-muted text-muted-foreground hover:bg-muted" },
}

function formatAge(sec: number | null): string {
  if (sec == null) return "—"
  if (sec < 60) return `${sec}s ago`
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`
  return `${Math.floor(sec / 86400)}d ago`
}

function formatTime(s: string | null | undefined) {
  if (!s) return "—"
  try {
    return new Date(s).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" })
  } catch {
    return s
  }
}

function showError(err: unknown) {
  toast({
    title: "Action failed",
    description: err instanceof Error ? err.message : String(err),
    variant: "destructive",
  })
}

/** Shows the city .env lines once, right after adding a site or replacing its key. */
function EnvSnippetDialog({
  data,
  onClose,
}: {
  data: { title: string; site: string; env: string } | null
  onClose: () => void
}) {
  const copy = async () => {
    if (!data) return
    try {
      await navigator.clipboard.writeText(data.env)
      toast({ title: "Copied", description: "Paste it into the city server's backend/.env" })
    } catch {
      toast({ title: "Copy failed", description: "Select the text and copy it manually.", variant: "destructive" })
    }
  }
  return (
    <Dialog open={!!data} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{data?.title}</DialogTitle>
          <DialogDescription>
            Add these lines to <code>backend/.env</code> on the {data?.site} server. The key is shown only
            now; if you lose it, use <b>New key</b>.
          </DialogDescription>
        </DialogHeader>
        <pre className="max-h-64 overflow-auto rounded-md border bg-muted p-3 text-xs leading-relaxed">
          {data?.env}
        </pre>
        <ol className="list-decimal space-y-1 pl-5 text-sm text-muted-foreground">
          <li>Paste the lines into the city's <code>backend/.env</code> (replace old sync lines).</li>
          <li>Restart the city backend.</li>
          <li>
            Start the sync workers on the city: <code>run_outbox_worker</code>, <code>run_media_worker</code>,{" "}
            <code>run_sync_heartbeat</code>, <code>run_reference_pull</code>.
          </li>
          <li>Come back here and click <b>Test connection</b>. Status turns Online within a minute.</li>
        </ol>
        <DialogFooter>
          <Button variant="outline" onClick={copy}>
            <Copy className="mr-2 h-4 w-4" /> Copy
          </Button>
          <Button onClick={onClose}>Done</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function AddSiteDialog({
  open,
  onOpenChange,
  options,
  existing,
  onAdded,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  options: { code: string; label: string }[]
  existing: Set<string>
  onAdded: (site: SyncSite, env: string) => void
}) {
  const [choice, setChoice] = useState("")
  const [newCode, setNewCode] = useState("")
  const [name, setName] = useState("")
  const [baseUrl, setBaseUrl] = useState("")

  const available = options.filter((o) => !existing.has(o.code))
  const code = choice === NEW_LOCATION ? newCode.trim().toUpperCase().replace(/\s+/g, "_") : choice

  const mutation = useMutation({
    mutationFn: () => addSyncSite({ location_code: code, name: name.trim(), base_url: baseUrl.trim() }),
    onSuccess: (data) => {
      onAdded(data.site, data.env_snippet)
      setChoice("")
      setNewCode("")
      setName("")
      setBaseUrl("")
      onOpenChange(false)
    },
    onError: showError,
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Add location</DialogTitle>
          <DialogDescription>
            Register a city server so it can send its records and images to this head office.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label>Location</Label>
            <Select
              value={choice}
              onValueChange={(v) => {
                setChoice(v)
                const opt = options.find((o) => o.code === v)
                if (opt) setName(opt.label)
              }}
            >
              <SelectTrigger>
                <SelectValue placeholder="Choose a location" />
              </SelectTrigger>
              <SelectContent>
                {available.map((o) => (
                  <SelectItem key={o.code} value={o.code}>
                    {o.label}
                  </SelectItem>
                ))}
                <SelectItem value={NEW_LOCATION}>Other (new location)…</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {choice === NEW_LOCATION && (
            <div className="space-y-2">
              <Label htmlFor="site-code">Location code</Label>
              <Input
                id="site-code"
                placeholder="e.g. BANNU"
                value={newCode}
                onChange={(e) => setNewCode(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Capital letters, digits or _ . It must match LOCATION_CODE in that city's .env.
              </p>
            </div>
          )}
          <div className="space-y-2">
            <Label htmlFor="site-name">Display name</Label>
            <Input id="site-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Bannu" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="site-url">Server address</Label>
            <Input
              id="site-url"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="192.168.120.13  or  http://192.168.120.13:8000"
            />
            <p className="text-xs text-muted-foreground">IP only means port 8000.</p>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={!code || !baseUrl.trim() || mutation.isPending} onClick={() => mutation.mutate()}>
            {mutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Add location
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function EditSiteDialog({ site, onClose }: { site: SyncSite | null; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState("")
  const [baseUrl, setBaseUrl] = useState("")
  const [loadedFor, setLoadedFor] = useState<string | null>(null)
  if (site && loadedFor !== site.location_code) {
    setLoadedFor(site.location_code)
    setName(site.name)
    setBaseUrl(site.base_url)
  }

  const mutation = useMutation({
    mutationFn: () => updateSyncSite(site!.location_code, { name: name.trim(), base_url: baseUrl.trim() }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY })
      setLoadedFor(null)
      onClose()
    },
    onError: showError,
  })

  return (
    <Dialog
      open={!!site}
      onOpenChange={(open) => {
        if (!open) {
          setLoadedFor(null)
          onClose()
        }
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Edit {site?.location_code}</DialogTitle>
          <DialogDescription>Change the display name or the server address.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="edit-name">Display name</Label>
            <Input id="edit-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="edit-url">Server address</Label>
            <Input id="edit-url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!name.trim() || !baseUrl.trim() || mutation.isPending} onClick={() => mutation.mutate()}>
            {mutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default function LocationsSyncPage() {
  const queryClient = useQueryClient()
  const isAdmin = normalizeRole(getStoredUser()?.role) === "ADMIN"
  const [addOpen, setAddOpen] = useState(false)
  const [editing, setEditing] = useState<SyncSite | null>(null)
  const [removing, setRemoving] = useState<SyncSite | null>(null)
  const [envDialog, setEnvDialog] = useState<{ title: string; site: string; env: string } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: QUERY_KEY,
    queryFn: fetchSyncSites,
    enabled: isAdmin,
    refetchInterval: 15000,
  })

  const existing = useMemo(() => new Set((data?.sites ?? []).map((s) => s.location_code)), [data])
  const refresh = () => queryClient.invalidateQueries({ queryKey: QUERY_KEY })

  const run = async (key: string, action: () => Promise<unknown>, success?: string) => {
    setBusy(key)
    try {
      await action()
      if (success) toast({ title: success })
      refresh()
    } catch (err) {
      showError(err)
    } finally {
      setBusy(null)
    }
  }

  const onTest = (site: SyncSite) =>
    run(`test:${site.location_code}`, async () => {
      const res = await testSyncSite(site.location_code)
      toast({
        title: res.ok ? `${site.name}: connected` : `${site.name}: not connected`,
        description: res.detail,
        variant: res.ok ? "default" : "destructive",
      })
    })

  const onTogglePause = (site: SyncSite) =>
    run(
      `pause:${site.location_code}`,
      () => updateSyncSite(site.location_code, { is_paused: !site.is_paused }),
      site.is_paused ? `${site.name} resumed` : `${site.name} paused — the city keeps its data queued`
    )

  const onFullHistory = (site: SyncSite) =>
    run(
      `history:${site.location_code}`,
      () => requestFullHistory(site.location_code),
      `${site.name} will start sending all old records and images on its next heartbeat`
    )

  const onNewKey = (site: SyncSite) =>
    run(`key:${site.location_code}`, async () => {
      const res = await rotateSyncSiteKey(site.location_code)
      setEnvDialog({ title: `New key for ${site.name}`, site: site.name, env: res.env_snippet })
    })

  const onRemove = (site: SyncSite) =>
    run(`remove:${site.location_code}`, () => removeSyncSite(site.location_code), `${site.name} removed`)

  if (!isAdmin) {
    return (
      <ModulePageLayout
        title="Locations & Sync"
        description="Connect city servers to the head office."
        breadcrumbs={[{ label: "System configuration" }, { label: "Locations & Sync" }]}
      >
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground">
            Only the Super Admin can manage locations.
          </CardContent>
        </Card>
      </ModulePageLayout>
    )
  }

  return (
    <ModulePageLayout
      title="Locations & Sync"
      description="Connect city servers to the head office and copy their records and images here."
      breadcrumbs={[{ label: "System configuration" }, { label: "Locations & Sync" }]}
      actions={
        <Button onClick={() => setAddOpen(true)} disabled={!data}>
          <Plus className="mr-2 h-4 w-4" /> Add location
        </Button>
      }
    >
      <div className="space-y-6">
        {data && (
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <Server className="h-5 w-5 text-[#3b82f6]" />
                This server: {data.hq.location_code} (head office)
              </CardTitle>
              <CardDescription>
                City servers send their data to <code>{data.hq.public_url}</code>. Status refreshes every 15 seconds.
              </CardDescription>
            </CardHeader>
            {data.unregistered.length > 0 && (
              <CardContent className="pt-0">
                <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>
                    Sending with an old .env key but not added here: <b>{data.unregistered.join(", ")}</b>. Add them
                    below to manage them from this page.
                  </span>
                </div>
              </CardContent>
            )}
          </Card>
        )}

        <Card>
          <CardHeader>
            <CardTitle>Locations</CardTitle>
            <CardDescription>Every city server that sends data to this head office.</CardDescription>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="flex items-center justify-center py-10 text-muted-foreground">
                <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading…
              </div>
            ) : error ? (
              <p className="py-6 text-center text-sm text-destructive">
                {error instanceof Error ? error.message : "Could not load locations."}
              </p>
            ) : !data?.sites.length ? (
              <div className="py-10 text-center text-muted-foreground">
                No locations yet. Click <b>Add location</b> to connect the first city.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Location</TableHead>
                      <TableHead>Server</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Last heartbeat</TableHead>
                      <TableHead className="text-right">Waiting at city</TableHead>
                      <TableHead className="text-right">Received here</TableHead>
                      <TableHead>Full history</TableHead>
                      <TableHead>Last test</TableHead>
                      <TableHead className="w-12" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.sites.map((site) => {
                      const style = STATE_STYLE[site.state] ?? STATE_STYLE.UNKNOWN
                      const rowBusy = busy?.endsWith(`:${site.location_code}`)
                      return (
                        <TableRow key={site.location_code}>
                          <TableCell>
                            <div className="font-medium">{site.name}</div>
                            <div className="text-xs text-muted-foreground">{site.location_code}</div>
                          </TableCell>
                          <TableCell className="font-mono text-xs">{site.base_url}</TableCell>
                          <TableCell>
                            <Badge className={style.className}>{style.label}</Badge>
                            {(site.dead_outbox > 0 || site.failed_media > 0) && (
                              <div className="mt-1 text-xs text-destructive">
                                {site.dead_outbox} failed records, {site.failed_media} failed images
                              </div>
                            )}
                          </TableCell>
                          <TableCell className="text-sm">{formatAge(site.heartbeat_age_sec)}</TableCell>
                          <TableCell className="text-right text-sm">
                            {site.pending_outbox} records
                            <div className="text-xs text-muted-foreground">{site.pending_media} images</div>
                          </TableCell>
                          <TableCell className="text-right text-sm">
                            {site.records_received.toLocaleString()} records
                            <div className="text-xs text-muted-foreground">
                              {site.media_received.toLocaleString()} images
                            </div>
                          </TableCell>
                          <TableCell className="text-sm">
                            {site.full_history === "DONE" ? (
                              <span title={formatTime(site.full_history_done_at)}>Sent</span>
                            ) : site.full_history === "REQUESTED" ? (
                              <span className="text-amber-600" title={formatTime(site.full_history_requested_at)}>
                                Requested…
                              </span>
                            ) : (
                              <span className="text-muted-foreground">Not requested</span>
                            )}
                          </TableCell>
                          <TableCell className="max-w-[16rem] text-xs">
                            {site.last_test_ok == null ? (
                              <span className="text-muted-foreground">Never</span>
                            ) : (
                              <span
                                className={`flex items-start gap-1 ${site.last_test_ok ? "text-emerald-600" : "text-destructive"}`}
                                title={site.last_test_detail}
                              >
                                {site.last_test_ok ? (
                                  <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                                ) : (
                                  <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                                )}
                                <span className="line-clamp-2">{site.last_test_detail}</span>
                              </span>
                            )}
                          </TableCell>
                          <TableCell>
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <Button variant="ghost" size="icon" disabled={rowBusy} aria-label="Actions">
                                  {rowBusy ? (
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                  ) : (
                                    <MoreHorizontal className="h-4 w-4" />
                                  )}
                                </Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end">
                                <DropdownMenuItem onClick={() => onTest(site)}>
                                  <Plug className="mr-2 h-4 w-4" /> Test connection
                                </DropdownMenuItem>
                                <DropdownMenuItem onClick={() => onFullHistory(site)}>
                                  <History className="mr-2 h-4 w-4" /> Send full history
                                </DropdownMenuItem>
                                <DropdownMenuItem onClick={() => onTogglePause(site)}>
                                  {site.is_paused ? (
                                    <>
                                      <Play className="mr-2 h-4 w-4" /> Resume sync
                                    </>
                                  ) : (
                                    <>
                                      <Pause className="mr-2 h-4 w-4" /> Pause sync
                                    </>
                                  )}
                                </DropdownMenuItem>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem onClick={() => setEditing(site)}>
                                  <Pencil className="mr-2 h-4 w-4" /> Edit
                                </DropdownMenuItem>
                                <DropdownMenuItem onClick={() => onNewKey(site)}>
                                  <KeyRound className="mr-2 h-4 w-4" /> New key
                                </DropdownMenuItem>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem className="text-destructive" onClick={() => setRemoving(site)}>
                                  <Trash2 className="mr-2 h-4 w-4" /> Remove
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
            )}
          </CardContent>
        </Card>
      </div>

      <AddSiteDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        options={data?.location_options ?? []}
        existing={existing}
        onAdded={(site, env) => {
          refresh()
          setEnvDialog({ title: `${site.name} added`, site: site.name, env })
        }}
      />
      <EditSiteDialog site={editing} onClose={() => setEditing(null)} />
      <EnvSnippetDialog data={envDialog} onClose={() => setEnvDialog(null)} />

      <AlertDialog open={!!removing} onOpenChange={(open) => !open && setRemoving(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove {removing?.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              Its key stops working at once and it can no longer send data. Records and images already received
              stay here. To stop it for a while instead, use <b>Pause sync</b>.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-white hover:bg-destructive/90"
              onClick={() => {
                if (removing) onRemove(removing)
                setRemoving(null)
              }}
            >
              Remove
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </ModulePageLayout>
  )
}
