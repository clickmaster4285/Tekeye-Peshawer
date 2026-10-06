import { useEffect, useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link, useNavigate, useSearchParams } from "react-router-dom"
import {
  Calendar,
  CheckCircle2,
  Code2,
  Eye,
  Filter,
  Monitor,
  Plus,
  RefreshCw,
  Search,
  Ticket,
  Timer,
  User,
  UserRound,
  X,
  Clock3,
} from "lucide-react"
import { ModulePageLayout } from "@/components/dashboard/module-page-layout"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { ROUTES, getSupportTicketPath } from "@/routes/config"
import {
  PRIORITY_COLORS,
  STATUS_COLORS,
  fetchSupportDashboard,
  fetchSupportMeta,
  fetchSupportTickets,
  type SupportTicket,
} from "@/lib/support-api"
import { getStoredUser } from "@/lib/auth"
import { TicketRowActions } from "@/pages/support/ticket-row-actions"
import { cn } from "@/lib/utils"

function isRequesterRole(role?: string | null) {
  const r = (role || "").trim().replace(/[\s-]+/g, "_").toUpperCase()
  return r === "ADMIN" || r === "LOCATION_ADMIN"
}

type QueueKey =
  | ""
  | "review"
  | "it"
  | "developer"
  | "sla"
  | "waiting_client"
  | "closed"
  | "my_requests"
  | "assigned_to_me"

type QueueTab = {
  key: QueueKey
  label: string
  icon: typeof Ticket
  countKey: string
}

const STAFF_TABS: QueueTab[] = [
  { key: "", label: "All Requests", icon: Ticket, countKey: "all" },
  { key: "review", label: "Review Queue", icon: Eye, countKey: "new" },
  { key: "it", label: "IT Queue", icon: Monitor, countKey: "it_queue" },
  { key: "developer", label: "Developer Queue", icon: Code2, countKey: "developer_queue" },
  { key: "sla", label: "SLA / Escalations", icon: Timer, countKey: "sla_breached" },
  { key: "waiting_client", label: "Waiting Client", icon: UserRound, countKey: "waiting_client" },
  { key: "closed", label: "Closed", icon: CheckCircle2, countKey: "closed" },
  { key: "my_requests", label: "My Requests", icon: Ticket, countKey: "my_requests" },
  { key: "assigned_to_me", label: "Assigned to Me", icon: User, countKey: "my_assigned" },
]

const REQUESTER_TABS: QueueTab[] = [
  { key: "my_requests", label: "My Requests", icon: Ticket, countKey: "my_requests" },
  { key: "waiting_client", label: "Waiting Client", icon: UserRound, countKey: "waiting_client" },
  { key: "closed", label: "Closed", icon: CheckCircle2, countKey: "closed" },
]

const QUEUE_TITLES: Record<string, string> = {
  "": "All Requests",
  review: "Review Queue",
  it: "IT Queue",
  developer: "Developer Queue",
  sla: "SLA / Escalations",
  waiting_client: "Waiting Client",
  closed: "Closed",
  my_requests: "My Requests",
  assigned_to_me: "Assigned to Me",
}

const REQUESTER_QUEUES = new Set(["", "my_requests", "waiting_client", "closed"])
const PAGE_SIZE = 10

function formatWhen(iso: string) {
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

function StatusBadge({ status, label }: { status: string; label: string }) {
  const Icon =
    status === "CANCELLED"
      ? X
      : status === "RESOLUTION_SUBMITTED" || status === "IN_PROGRESS" || status === "ON_HOLD"
        ? Clock3
        : status === "CLOSED"
          ? CheckCircle2
          : null

  return (
    <Badge
      className={cn("inline-flex items-center gap-1 font-normal", STATUS_COLORS[status] || "")}
      variant="secondary"
    >
      {Icon ? <Icon className="h-3 w-3" /> : null}
      {label}
    </Badge>
  )
}

export default function SupportRequestList() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const queue = (params.get("queue") || "") as QueueKey
  const search = params.get("search") || ""
  const [searchDraft, setSearchDraft] = useState(search)
  const [page, setPage] = useState(1)

  useEffect(() => {
    setSearchDraft(search)
  }, [search])

  useEffect(() => {
    setPage(1)
  }, [queue, search])

  const metaQ = useQuery({
    queryKey: ["support", "meta"],
    queryFn: fetchSupportMeta,
  })
  const caps = metaQ.data?.capabilities
  // Prefer API caps; until loaded, use stored login role so staff filters don't flash.
  const requesterOnly =
    caps != null
      ? Boolean(caps.is_requester_only)
      : isRequesterRole(getStoredUser()?.role)

  const actionMut = useMutation({
    mutationFn: (fn: () => Promise<unknown>) => fn(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["support"] })
    },
  })

  const dashQ = useQuery({
    queryKey: ["support", "dashboard"],
    queryFn: fetchSupportDashboard,
    refetchInterval: 15000,
  })

  useEffect(() => {
    if (!requesterOnly) return
    if (!queue || !REQUESTER_QUEUES.has(queue)) {
      const next = new URLSearchParams(params)
      next.set("queue", "my_requests")
      setParams(next, { replace: true })
    }
  }, [requesterOnly, queue, params, setParams])

  const effectiveQueue: QueueKey =
    requesterOnly && (!queue || !REQUESTER_QUEUES.has(queue))
      ? "my_requests"
      : queue

  const queryParams = useMemo(
    () => ({
      queue: effectiveQueue || undefined,
      search: search || undefined,
      ...(requesterOnly ? { mine: "1" } : {}),
    }),
    [effectiveQueue, search, requesterOnly]
  )

  const { data = [], isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["support", "tickets", queryParams],
    queryFn: () => fetchSupportTickets(queryParams),
    refetchInterval: 12000,
  })

  const title = requesterOnly
    ? QUEUE_TITLES[effectiveQueue] || "My Requests"
    : QUEUE_TITLES[queue] || "All Requests"

  const tabs = requesterOnly ? REQUESTER_TABS : STAFF_TABS
  const activeKey = requesterOnly ? effectiveQueue : queue

  const counts = (dashQ.data?.counts || {}) as Record<string, number>
  const allCount = useMemo(() => {
    // Approximate "all" as open + closed (cancelled still appears in unfiltered list)
    const open = Number(counts.total_open || 0)
    const closed = Number(counts.closed || 0)
    if (activeKey === "" && data.length > open + closed) return data.length
    return open + closed
  }, [counts, activeKey, data.length])

  const tabCount = (tab: QueueTab) => {
    if (tab.countKey === "all") return allCount
    return Number(counts[tab.countKey] || 0)
  }

  const total = data.length
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const safePage = Math.min(page, totalPages)
  const start = total === 0 ? 0 : (safePage - 1) * PAGE_SIZE + 1
  const end = Math.min(safePage * PAGE_SIZE, total)
  const pageRows = data.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE)

  const applySearch = () => {
    const next = new URLSearchParams(params)
    const v = searchDraft.trim()
    if (v) next.set("search", v)
    else next.delete("search")
    setParams(next)
  }

  const setQueue = (key: QueueKey) => {
    const next = new URLSearchParams(params)
    if (key) next.set("queue", key)
    else next.delete("queue")
    setParams(next)
  }

  return (
    <ModulePageLayout
      title={title}
      description="Role-filtered queues for Support, IT, Developer, and clients."
      breadcrumbs={[
        { label: "Requests & Support", href: ROUTES.SUPPORT_DASHBOARD },
        { label: title },
      ]}
      actions={
        <div className="flex gap-2">
          <Button
            variant="outline"
            className="border-slate-200 bg-white"
            onClick={() => refetch()}
            disabled={isFetching}
          >
            <RefreshCw className={cn("mr-2 h-4 w-4", isFetching && "animate-spin")} />
            Refresh
          </Button>
          <Button asChild className="bg-[#155DFC] hover:bg-[#1248c9]">
            <Link to={ROUTES.SUPPORT_CREATE}>
              <Plus className="mr-2 h-4 w-4" />
              New Request
            </Link>
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        {/* Queue tabs */}
        <div className="flex flex-wrap gap-2">
          {tabs.map((tab) => {
            const active = activeKey === tab.key
            const Icon = tab.icon
            const count = tabCount(tab)
            return (
              <button
                key={tab.key || "all"}
                type="button"
                onClick={() => setQueue(tab.key)}
                className={cn(
                  "inline-flex items-center gap-2 rounded-full border px-3.5 py-2 text-sm font-medium transition",
                  active
                    ? "border-[#155DFC] bg-[#155DFC] text-white shadow-sm"
                    : "border-[#E5E7EB] bg-white text-[#4B5563] hover:border-[#155DFC]/40 hover:text-[#155DFC]"
                )}
              >
                <Icon className="h-3.5 w-3.5" />
                <span>{tab.label}</span>
                <span
                  className={cn(
                    "min-w-[1.25rem] rounded-full px-1.5 py-0.5 text-center text-[11px] font-semibold tabular-nums",
                    active ? "bg-[#1248c9] text-white" : "bg-[#EBF2FF] text-[#2860C8]"
                  )}
                >
                  {count}
                </span>
              </button>
            )
          })}
        </div>

        {/* Search + filter */}
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <Input
              className="h-10 border-slate-200 bg-white pl-9"
              placeholder="Search ticket #, title, site, asset..."
              value={searchDraft}
              onChange={(e) => setSearchDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") applySearch()
              }}
            />
          </div>
          <Button
            variant="outline"
            className="h-10 border-slate-200 bg-white"
            onClick={applySearch}
          >
            <Filter className="mr-2 h-4 w-4" />
            Filter
          </Button>
        </div>

        {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {error && <p className="text-sm text-red-600">{(error as Error).message}</p>}

        {/* Table card */}
        {!isLoading && !error && (
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="border-slate-200 bg-[#EBF2FF]/70 hover:bg-[#EBF2FF]/70">
                    <TableHead className="pl-4 font-semibold text-slate-700">Ticket</TableHead>
                    <TableHead className="font-semibold text-slate-700">Title</TableHead>
                    <TableHead className="font-semibold text-slate-700">Status</TableHead>
                    <TableHead className="font-semibold text-slate-700">Priority</TableHead>
                    <TableHead className="font-semibold text-slate-700">Dept</TableHead>
                    <TableHead className="font-semibold text-slate-700">Site / Asset</TableHead>
                    <TableHead className="font-semibold text-slate-700">Requester</TableHead>
                    <TableHead className="font-semibold text-slate-700">Created</TableHead>
                    <TableHead className="pr-4 text-right font-semibold text-slate-700">
                      Actions
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pageRows.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={9} className="py-12 text-center text-muted-foreground">
                        No requests in this queue.
                      </TableCell>
                    </TableRow>
                  )}
                  {pageRows.map((t: SupportTicket) => (
                    <TableRow
                      key={t.id}
                      className="cursor-pointer border-slate-100 hover:bg-[#EBF2FF]/50"
                      onClick={() => navigate(getSupportTicketPath(t.id))}
                    >
                      <TableCell className="pl-4">
                        <span className="inline-flex items-center gap-1.5 font-medium text-[#155DFC]">
                          <Ticket className="h-3.5 w-3.5 shrink-0" />
                          {t.ticket_number}
                        </span>
                        {t.sla_breached && (
                          <Badge className="ml-2 bg-red-100 text-red-800" variant="secondary">
                            SLA
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="max-w-[240px]">
                        <span className="line-clamp-2 text-sm text-slate-800">{t.title}</span>
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={t.status} label={t.status_label} />
                      </TableCell>
                      <TableCell>
                        <Badge
                          className={cn(
                            "border font-semibold",
                            PRIORITY_COLORS[t.priority] || "bg-slate-100 text-slate-700"
                          )}
                          variant="secondary"
                        >
                          {t.priority}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-sm text-slate-700">
                        {t.department_label || "—"}
                      </TableCell>
                      <TableCell className="max-w-[180px] truncate text-sm text-slate-600">
                        {[t.site_name, t.asset_label].filter(Boolean).join(" · ") || "—"}
                      </TableCell>
                      <TableCell>
                        <span className="inline-flex items-center gap-1.5 text-sm text-slate-700">
                          <User className="h-3.5 w-3.5 text-slate-400" />
                          {t.requester_name}
                        </span>
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-xs text-slate-600">
                        <span className="inline-flex items-center gap-1.5">
                          <Calendar className="h-3.5 w-3.5 text-slate-400" />
                          {formatWhen(t.created_at)}
                        </span>
                      </TableCell>
                      <TableCell
                        className="pr-4"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <TicketRowActions
                          ticket={t}
                          caps={caps}
                          busy={actionMut.isPending}
                          onAction={(fn) => actionMut.mutate(fn)}
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>

            {/* Pagination footer */}
            <div className="flex flex-col gap-3 border-t border-slate-100 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm text-slate-500">
                {total === 0
                  ? "Showing 0 of 0 requests"
                  : `Showing ${start} - ${end} of ${total} requests`}
              </p>
              <div className="flex items-center gap-1">
                <Button
                  size="icon"
                  variant="outline"
                  className="h-8 w-8 border-slate-200"
                  disabled={safePage <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  ‹
                </Button>
                {Array.from({ length: totalPages }, (_, i) => i + 1)
                  .slice(0, 7)
                  .map((n) => (
                    <Button
                      key={n}
                      size="icon"
                      variant={n === safePage ? "default" : "outline"}
                      className={cn(
                        "h-8 w-8",
                        n === safePage
                          ? "bg-[#155DFC] hover:bg-[#1248c9]"
                          : "border-slate-200"
                      )}
                      onClick={() => setPage(n)}
                    >
                      {n}
                    </Button>
                  ))}
                <Button
                  size="icon"
                  variant="outline"
                  className="h-8 w-8 border-slate-200"
                  disabled={safePage >= totalPages}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                >
                  ›
                </Button>
              </div>
            </div>
          </div>
        )}
      </div>
    </ModulePageLayout>
  )
}
