import { useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link, useNavigate, useParams } from "react-router-dom"
import {
  ArrowLeft,
  Building2,
  CalendarDays,
  Check,
  CheckCircle2,
  ClipboardList,
  Clock3,
  FileText,
  Flag,
  Home,
  Info,
  ListChecks,
  Reply,
  User,
  UserPlus,
  Download,
  FileImage,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { ROUTES } from "@/routes/config"
import {
  assignTicket,
  cancelTicket,
  clientConfirmTicket,
  fetchAssignableUsers,
  fetchSupportMeta,
  fetchSupportTicket,
  holdTicket,
  startTicket,
  submitResolution,
  triageTicket,
  verifyTicket,
  type SupportTicket,
} from "@/lib/support-api"
import { cn } from "@/lib/utils"
import { TicketChatPanel } from "@/pages/support/TicketChat"

function formatDate(iso?: string | null) {
  if (!iso) return "—"
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
    })
  } catch {
    return iso
  }
}

function formatShort(iso?: string | null) {
  if (!iso) return ""
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    })
  } catch {
    return ""
  }
}

function statusDisplay(status: string) {
  if (["NEW", "TRIAGED", "ASSIGNED", "REOPENED"].includes(status)) return "Open"
  if (["IN_PROGRESS", "ON_HOLD"].includes(status)) return "In Progress"
  if (["RESOLUTION_SUBMITTED", "SUPPORT_VERIFIED", "PENDING_CLIENT_CONFIRM"].includes(status))
    return "Resolved"
  if (status === "CLOSED") return "Closed"
  if (status === "EXPIRED") return "Expired"
  if (status === "CANCELLED") return "Cancelled"
  return status
}

function priorityLabel(p: string) {
  if (p === "P1") return "Critical"
  if (p === "P2") return "High"
  if (p === "P3") return "Medium"
  if (p === "P4") return "Low"
  return p
}

function departmentLabel(d: string) {
  if (d === "IT") return "IT Support"
  if (d === "DEVELOPER") return "Developer"
  if (d === "SUPPORT") return "Support"
  if (d === "OPERATIONS") return "Operations"
  if (d === "ADMIN") return "Admin"
  return d === "UNASSIGNED" ? "Unassigned" : d
}

function DetailField({
  icon: Icon,
  label,
  children,
}: {
  icon: typeof User
  label: string
  children: ReactNode
}) {
  return (
    <div className="min-w-0">
      <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-[#6B7280]">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <div className="truncate text-sm font-medium text-[#111827]">{children}</div>
    </div>
  )
}

function StatusStepper({ ticket }: { ticket: SupportTicket }) {
  const stepIndex = useMemo(() => {
    const s = ticket.status
    if (s === "CLOSED") return 3
    if (["RESOLUTION_SUBMITTED", "SUPPORT_VERIFIED", "PENDING_CLIENT_CONFIRM"].includes(s)) return 2
    if (["IN_PROGRESS", "ON_HOLD", "ASSIGNED", "TRIAGED"].includes(s)) return 1
    if (s === "EXPIRED" || s === "CANCELLED") return 0
    return 0
  }, [ticket.status])

  const steps = [
    { label: "Created", at: ticket.created_at },
    {
      label: "In Progress",
      at:
        ticket.assigned_at ||
        (stepIndex >= 1
          ? ticket.events?.find((e) =>
            ["started", "assigned", "triaged"].includes(e.event_type)
          )?.created_at
          : null),
    },
    {
      label: "Resolved",
      at: ticket.resolution_submitted_at || ticket.verified_at,
    },
    { label: "Closed", at: ticket.closed_at },
  ]

  return (
    <div className="px-1 pt-1">
      <div className="relative flex justify-between">
        <div className="absolute left-[12%] right-[12%] top-4 h-0.5 bg-[#E5E7EB]" />
        <div
          className="absolute left-[12%] top-4 h-0.5 bg-[#22C55E] transition-all"
          style={{ width: `${Math.min(stepIndex, 3) * (76 / 3)}%` }}
        />
        {steps.map((step, i) => {
          const done = i < stepIndex || (i === stepIndex && ticket.status === "CLOSED" && i === 3)
          const active = i === stepIndex && ticket.status !== "CLOSED"
          const closedDone = ticket.status === "CLOSED" && i <= 3
          const complete = done || (closedDone && i < 3) || (ticket.status === "CLOSED" && i === 3)
          return (
            <div key={step.label} className="relative z-10 flex w-1/4 flex-col items-center text-center">
              <div
                className={cn(
                  "flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold",
                  complete || (ticket.status === "CLOSED" && i === 3)
                    ? "bg-[#22C55E] text-white"
                    : active
                      ? "bg-[#2563EB] text-white"
                      : "bg-[#E5E7EB] text-[#6B7280]"
                )}
              >
                {complete || (ticket.status === "CLOSED" && i === 3) ? (
                  <Check className="h-4 w-4" strokeWidth={3} />
                ) : (
                  i + 1
                )}
              </div>
              <p
                className={cn(
                  "mt-2 text-xs font-semibold",
                  active || complete ? "text-[#111827]" : "text-[#9CA3AF]"
                )}
              >
                {step.label}
              </p>
              <p className="mt-0.5 text-[10px] text-[#9CA3AF]">
                {step.at ? formatShort(step.at) : "—"}
              </p>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function SupportRequestDetail() {
  const { id } = useParams()
  const ticketId = Number(id)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const replyRef = useRef<HTMLTextAreaElement>(null)

  const ticketQ = useQuery({
    queryKey: ["support", "ticket", ticketId],
    queryFn: () => fetchSupportTicket(ticketId),
    enabled: Number.isFinite(ticketId),
    refetchInterval: 10000,
  })
  const metaQ = useQuery({
    queryKey: ["support", "meta"],
    queryFn: fetchSupportMeta,
  })

  const ticket = ticketQ.data
  const caps = metaQ.data?.capabilities
  const [category, setCategory] = useState("")
  const [priority, setPriority] = useState("")
  const [department, setDepartment] = useState("")
  const [assigneeId, setAssigneeId] = useState("")
  const [resolution, setResolution] = useState("")
  const [verifyNotes, setVerifyNotes] = useState("")
  const [clientNotes, setClientNotes] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [priorityOpen, setPriorityOpen] = useState(false)
  const [assignOpen, setAssignOpen] = useState(false)
  const [handleOpen, setHandleOpen] = useState(false)

  useEffect(() => {
    if (!ticket) return
    setCategory(ticket.category || ticket.suggested_category || "")
    setPriority(ticket.priority || ticket.suggested_priority || "")
    setDepartment(
      ticket.department !== "UNASSIGNED"
        ? ticket.department
        : ticket.suggested_department && ticket.suggested_department !== "UNASSIGNED"
          ? ticket.suggested_department
          : "SUPPORT"
    )
  }, [ticket])

  const assignableQ = useQuery({
    queryKey: ["support", "assignable", department],
    queryFn: () => fetchAssignableUsers(department === "UNASSIGNED" ? undefined : department),
    enabled: Boolean(caps?.can_support_triage && assignOpen),
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["support"] })
  }

  const run = async (fn: () => Promise<unknown>) => {
    setError(null)
    try {
      await fn()
      invalidate()
      await ticketQ.refetch()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  if (ticketQ.isLoading) {
    return (
      <div className="p-6 text-sm text-[#6B7280]">Loading ticket…</div>
    )
  }

  if (!ticket) {
    return (
      <div className="p-6">
        <p className="text-sm text-red-600">Ticket not found.</p>
        <Button asChild className="mt-3" variant="outline">
          <Link to={ROUTES.SUPPORT_ALL}>Back to list</Link>
        </Button>
      </div>
    )
  }

  const canTriage = Boolean(caps?.can_support_triage)
  const canHandle =
    (ticket.department === "IT" && caps?.can_handle_it) ||
    (ticket.department === "DEVELOPER" && caps?.can_handle_developer) ||
    canTriage
  const isRequesterView = Boolean(caps?.is_requester_only)
  const ticketActive = !["EXPIRED", "CLOSED", "CANCELLED"].includes(ticket.status)
  const uiStatus = statusDisplay(ticket.status)
  const pLabel = priorityLabel(ticket.priority)
  const deptLabel = departmentLabel(ticket.department)

  const remainingH = Math.max(0, Math.floor((ticket.validity_remaining_seconds || 0) / 3600))
  const remainingM = Math.max(
    0,
    Math.floor(((ticket.validity_remaining_seconds || 0) % 3600) / 60)
  )

  return (
    <div className="min-h-full bg-[#F3F4F6] px-4 py-5 sm:px-6 lg:px-8">
      {/* Breadcrumb */}
      <nav className="mb-4 flex items-center gap-1.5 text-sm text-[#6B7280]">
        <Link to={ROUTES.DASHBOARD} className="inline-flex items-center hover:text-[#2563EB]">
          <Home className="h-4 w-4" />
        </Link>
        <span className="text-[#D1D5DB]">›</span>
        <Link to={ROUTES.SUPPORT_ALL} className="hover:text-[#2563EB]">
          Support
        </Link>
        <span className="text-[#D1D5DB]">›</span>
        <span className="font-medium text-[#111827]">Ticket Details</span>
      </nav>

      {/* Header card */}
      <div className="mb-5 rounded-xl border border-[#E5E7EB] bg-white px-5 py-4 shadow-sm">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="flex items-start gap-3">
              <button
                type="button"
                onClick={() => navigate(-1)}
                className="mt-0.5 rounded-lg p-1.5 text-[#6B7280] hover:bg-[#F3F4F6] hover:text-[#111827]"
                aria-label="Back"
              >
                <ArrowLeft className="h-5 w-5" />
              </button>
              <div>
                <h1 className="text-xl font-bold tracking-tight text-[#111827] sm:text-2xl">
                  #{ticket.ticket_number}
                </h1>
                <p className="mt-1 text-sm text-[#4B5563] sm:text-base">{ticket.title}</p>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <span
                    className={cn(
                      "rounded-full border px-2.5 py-0.5 text-xs font-semibold",
                      uiStatus === "Open"
                        ? "border-[#93C5FD] bg-[#EFF6FF] text-[#1D4ED8]"
                        : uiStatus === "In Progress"
                          ? "border-[#FCD34D] bg-[#FFFBEB] text-[#B45309]"
                          : uiStatus === "Resolved"
                            ? "border-[#6EE7B7] bg-[#ECFDF5] text-[#047857]"
                            : uiStatus === "Closed"
                              ? "border-[#86EFAC] bg-[#F0FDF4] text-[#15803D]"
                              : "border-[#FCA5A5] bg-[#FEF2F2] text-[#B91C1C]"
                    )}
                  >
                    {uiStatus}
                  </span>
                  <span
                    className={cn(
                      "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold",
                      ticket.priority === "P1" || ticket.priority === "P2"
                        ? "border-[#FECACA] bg-[#FEF2F2] text-[#B91C1C]"
                        : "border-[#FDE68A] bg-[#FFFBEB] text-[#B45309]"
                    )}
                  >
                    <Flag className="h-3 w-3" />
                    {pLabel} Priority
                  </span>
                  <span className="rounded-full border border-[#BFDBFE] bg-[#F8FAFC] px-2.5 py-0.5 text-xs font-semibold text-[#1E40AF]">
                    {deptLabel}
                  </span>
                  {ticketActive && ticket.expires_at && (
                    <span className="inline-flex items-center gap-1 rounded-full border border-[#E5E7EB] bg-[#F9FAFB] px-2.5 py-0.5 text-xs text-[#6B7280]">
                      <Clock3 className="h-3 w-3" />
                      Valid {remainingH}h {remainingM}m left
                    </span>
                  )}
                </div>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 text-sm text-[#6B7280] lg:pt-1">
            <CalendarDays className="h-4 w-4 shrink-0" />
            <span>Created on {formatDate(ticket.created_at)}</span>
          </div>
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        {/* LEFT */}
        <div className="space-y-5">
          {/* Ticket Details */}
          <div className="rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
            <div className="flex items-center gap-2 border-b border-[#E5E7EB] px-5 py-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#EFF6FF] text-[#2563EB]">
                <ClipboardList className="h-4 w-4" />
              </div>
              <h2 className="text-base font-semibold text-[#111827]">Ticket Details</h2>
            </div>
            <div className="grid gap-5 px-5 py-5 sm:grid-cols-2 lg:grid-cols-3">
              <DetailField icon={User} label="Requester Name">
                {ticket.requester_name}
              </DetailField>
              <DetailField icon={User} label="Assigned To">
                {ticket.assigned_to_name
                  ? `${ticket.assigned_to_name}${ticket.department !== "UNASSIGNED" ? ` (${deptLabel})` : ""}`
                  : "Unassigned"}
              </DetailField>
              <DetailField icon={Clock3} label="Last Updated">
                {formatDate(ticket.updated_at)}
              </DetailField>
              <DetailField icon={Building2} label="Site / Department">
                {ticket.site_name || "—"}
              </DetailField>
              <DetailField icon={CalendarDays} label="Created On">
                {formatDate(ticket.created_at)}
              </DetailField>
              <DetailField icon={Flag} label="Priority">
                <span
                  className={cn(
                    "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-bold",
                    ticket.priority === "P1" || ticket.priority === "P2"
                      ? "bg-[#FEE2E2] text-[#B91C1C]"
                      : "bg-[#FEF3C7] text-[#B45309]"
                  )}
                >
                  {ticket.priority} {pLabel}
                </span>
              </DetailField>
            </div>
            {ticket.description && (
              <div className="border-t border-[#E5E7EB] px-5 py-4">
                <p className="mb-1 text-xs font-medium text-[#6B7280]">Description</p>
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-[#374151]">
                  {ticket.description}
                </p>
              </div>
            )}
            {ticket.asset_label && (
              <div className="border-t border-[#E5E7EB] px-5 py-3 text-sm text-[#4B5563]">
                <span className="font-medium text-[#111827]">Asset:</span> {ticket.asset_label}
              </div>
            )}
          </div>

          <TicketChatPanel ticket={ticket} replyFocusRef={replyRef} />
        </div>

        {/* RIGHT SIDEBAR */}
        <aside className="space-y-5">
          {/* Ticket Status */}
          <div className="rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
            <div className="flex items-center gap-2 border-b border-[#E5E7EB] px-5 py-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#EFF6FF] text-[#2563EB]">
                <ListChecks className="h-4 w-4" />
              </div>
              <h2 className="text-base font-semibold text-[#111827]">Ticket Status</h2>
            </div>
            <div className="px-3 py-5">
              <StatusStepper ticket={ticket} />
            </div>
          </div>

          {/* Quick Actions */}
          <div className="rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
            <div className="flex items-center gap-2 border-b border-[#E5E7EB] px-5 py-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#EFF6FF] text-[#2563EB]">
                <CheckCircle2 className="h-4 w-4" />
              </div>
              <h2 className="text-base font-semibold text-[#111827]">Quick Actions</h2>
            </div>
            <div className="space-y-2.5 px-4 py-4">
              <Button
                className="h-11 w-full justify-start gap-2 bg-[#2563EB] text-white hover:bg-[#1D4ED8]"
                onClick={() => replyRef.current?.focus()}
                disabled={!ticket.can_chat}
              >
                <Reply className="h-4 w-4" />
                Reply to Ticket
              </Button>

              {canTriage && ticketActive && (
                <Button
                  variant="outline"
                  className="h-11 w-full justify-start gap-2 border-[#BFDBFE] text-[#1D4ED8] hover:bg-[#EFF6FF]"
                  onClick={() => setPriorityOpen(true)}
                >
                  <Flag className="h-4 w-4" />
                  Change Priority
                </Button>
              )}

              {canTriage && ticketActive && (
                <Button
                  variant="outline"
                  className="h-11 w-full justify-start gap-2 border-[#BFDBFE] text-[#1D4ED8] hover:bg-[#EFF6FF]"
                  onClick={() => setAssignOpen(true)}
                >
                  <UserPlus className="h-4 w-4" />
                  Assign to Staff
                </Button>
              )}

              {canHandle &&
                ticketActive &&
                ["ASSIGNED", "IN_PROGRESS", "ON_HOLD", "TRIAGED", "REOPENED"].includes(
                  ticket.status
                ) && (
                  <Button
                    variant="outline"
                    className="h-11 w-full justify-start gap-2 border-[#BFDBFE] text-[#1D4ED8] hover:bg-[#EFF6FF]"
                    onClick={() => setHandleOpen(true)}
                  >
                    <CheckCircle2 className="h-4 w-4" />
                    Handle / Resolve
                  </Button>
                )}

              {canTriage && ticketActive && ticket.status === "RESOLUTION_SUBMITTED" && (
                <>
                  <Button
                    className="h-11 w-full justify-start gap-2 bg-[#059669] hover:bg-[#047857]"
                    onClick={() =>
                      run(() =>
                        verifyTicket(ticket.id, {
                          approved: true,
                          verification_notes: verifyNotes || "Verified by Support",
                        })
                      )
                    }
                  >
                    <Check className="h-4 w-4" />
                    Verify Resolution
                  </Button>
                  <Button
                    variant="outline"
                    className="h-11 w-full justify-start gap-2 border-red-200 text-red-700"
                    onClick={() =>
                      run(() =>
                        verifyTicket(ticket.id, {
                          approved: false,
                          verification_notes: "Rejected — needs more work",
                        })
                      )
                    }
                  >
                    Reject Resolution
                  </Button>
                </>
              )}

              {(isRequesterView || canTriage) &&
                ticketActive &&
                ticket.status === "PENDING_CLIENT_CONFIRM" && (
                  <>
                    <Button
                      className="h-11 w-full justify-start gap-2 bg-[#059669] hover:bg-[#047857]"
                      onClick={() =>
                        run(() =>
                          clientConfirmTicket(ticket.id, {
                            accepted: true,
                            client_notes: clientNotes,
                          })
                        )
                      }
                    >
                      <Check className="h-4 w-4" />
                      Accept & Close
                    </Button>
                    <Input
                      className="text-sm"
                      placeholder="Optional confirmation notes"
                      value={clientNotes}
                      onChange={(e) => setClientNotes(e.target.value)}
                    />
                  </>
                )}

              {(canTriage || isRequesterView) && ticketActive && (
                <Button
                  variant="outline"
                  className="h-11 w-full justify-start gap-2 border-[#BFDBFE] text-[#1D4ED8] hover:bg-[#EFF6FF]"
                  onClick={() => {
                    if (window.confirm("Close / cancel this ticket?")) {
                      run(() => cancelTicket(ticket.id, "Closed from Quick Actions"))
                    }
                  }}
                >
                  <Check className="h-4 w-4" />
                  Close Ticket
                </Button>
              )}
            </div>
          </div>

          {/* Ticket Information */}
          <div className="rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
            <div className="flex items-center gap-2 border-b border-[#E5E7EB] px-5 py-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#EFF6FF] text-[#2563EB]">
                <Info className="h-4 w-4" />
              </div>
              <h2 className="text-base font-semibold text-[#111827]">Ticket Information</h2>
            </div>
            <dl className="divide-y divide-[#F3F4F6] px-5">
              <div className="flex items-center justify-between gap-3 py-3 text-sm">
                <dt className="flex items-center gap-2 text-[#6B7280]">
                  <FileText className="h-3.5 w-3.5" />
                  Ticket ID
                </dt>
                <dd className="font-semibold text-[#111827]">#{ticket.ticket_number}</dd>
              </div>
              <div className="flex items-center justify-between gap-3 py-3 text-sm">
                <dt className="flex items-center gap-2 text-[#6B7280]">
                  <ClipboardList className="h-3.5 w-3.5" />
                  Category
                </dt>
                <dd className="font-medium text-[#111827]">{ticket.category_label}</dd>
              </div>
              <div className="flex items-center justify-between gap-3 py-3 text-sm">
                <dt className="flex items-center gap-2 text-[#6B7280]">
                  <ListChecks className="h-3.5 w-3.5" />
                  Status
                </dt>
                <dd>
                  <span className="rounded-full border border-[#93C5FD] bg-[#EFF6FF] px-2.5 py-0.5 text-xs font-semibold text-[#1D4ED8]">
                    {uiStatus}
                  </span>
                </dd>
              </div>
              <div className="flex items-center justify-between gap-3 py-3 text-sm">
                <dt className="flex items-center gap-2 text-[#6B7280]">
                  <Flag className="h-3.5 w-3.5" />
                  Priority
                </dt>
                <dd>
                  <span
                    className={cn(
                      "rounded-full px-2.5 py-0.5 text-xs font-semibold",
                      ticket.priority === "P1" || ticket.priority === "P2"
                        ? "bg-[#FEE2E2] text-[#B91C1C]"
                        : "bg-[#FEF3C7] text-[#B45309]"
                    )}
                  >
                    {pLabel}
                  </span>
                </dd>
              </div>
              <div className="flex items-center justify-between gap-3 py-3 text-sm">
                <dt className="flex items-center gap-2 text-[#6B7280]">
                  <Building2 className="h-3.5 w-3.5" />
                  Department
                </dt>
                <dd className="font-medium text-[#111827]">{deptLabel}</dd>
              </div>
            </dl>
          </div>

          {/* Related Files */}
          <div className="rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
            <div className="flex items-center gap-2 border-b border-[#E5E7EB] px-5 py-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#EFF6FF] text-[#2563EB]">
                <FileImage className="h-4 w-4" />
              </div>
              <h2 className="text-base font-semibold text-[#111827]">Related Files</h2>
            </div>
            <div className="px-4 py-4">
              {ticket.asset_label ? (
                <div className="flex items-center gap-3 rounded-xl border border-[#BFDBFE] bg-[#EFF6FF] px-3 py-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-white text-[#2563EB] shadow-sm">
                    <FileText className="h-5 w-5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-[#111827]">
                      {ticket.asset_label}
                    </p>
                    <p className="text-xs text-[#6B7280]">Linked asset / camera</p>
                  </div>
                  <Download className="h-4 w-4 shrink-0 text-[#2563EB]" />
                </div>
              ) : (
                <p className="rounded-xl border border-dashed border-[#D1D5DB] px-3 py-6 text-center text-sm text-[#9CA3AF]">
                  No files attached yet
                </p>
              )}
            </div>
          </div>
        </aside>
      </div>

      {/* Change Priority dialog */}
      <Dialog open={priorityOpen} onOpenChange={setPriorityOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Change Priority & Category</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label>Category</Label>
              <Select value={category} onValueChange={setCategory}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(metaQ.data?.categories || []).map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>Priority</Label>
              <Select value={priority} onValueChange={setPriority}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(metaQ.data?.priorities || []).map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>Department</Label>
              <Select value={department} onValueChange={setDepartment}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(metaQ.data?.departments || [])
                    .filter((d) => d.value !== "UNASSIGNED")
                    .map((o) => (
                      <SelectItem key={o.value} value={o.value}>
                        {o.label}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
            <Button
              className="w-full bg-[#2563EB] hover:bg-[#1D4ED8]"
              onClick={async () => {
                await run(() =>
                  triageTicket(ticket.id, { category, priority, department })
                )
                setPriorityOpen(false)
              }}
            >
              Save changes
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Assign dialog */}
      <Dialog open={assignOpen} onOpenChange={setAssignOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Assign to Staff</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label>Department</Label>
              <Select value={department} onValueChange={setDepartment}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(metaQ.data?.departments || [])
                    .filter((d) => d.value !== "UNASSIGNED")
                    .map((o) => (
                      <SelectItem key={o.value} value={o.value}>
                        {o.label}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>Staff member</Label>
              <Select value={assigneeId} onValueChange={setAssigneeId}>
                <SelectTrigger>
                  <SelectValue placeholder="Select staff or queue" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="queue">Department queue</SelectItem>
                  {(assignableQ.data || []).map((u) => (
                    <SelectItem key={u.id} value={String(u.id)}>
                      {u.full_name || u.username} ({u.role})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button
              className="w-full bg-[#2563EB] hover:bg-[#1D4ED8]"
              onClick={async () => {
                await run(() =>
                  assignTicket(ticket.id, {
                    department,
                    assigned_to:
                      assigneeId && assigneeId !== "queue" ? Number(assigneeId) : null,
                  })
                )
                setAssignOpen(false)
              }}
            >
              Assign ticket
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Handle / Resolve dialog */}
      <Dialog open={handleOpen} onOpenChange={setHandleOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Handle Ticket</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            {ticket.status !== "IN_PROGRESS" && (
              <Button
                className="w-full"
                variant="secondary"
                onClick={() => run(() => startTicket(ticket.id))}
              >
                Start work
              </Button>
            )}
            <Button
              className="w-full"
              variant="outline"
              onClick={() => run(() => holdTicket(ticket.id))}
            >
              Put on hold
            </Button>
            <div className="space-y-1.5">
              <Label>Resolution notes</Label>
              <Textarea
                rows={4}
                placeholder="Work completed / solution provided…"
                value={resolution}
                onChange={(e) => setResolution(e.target.value)}
              />
            </div>
            <Button
              className="w-full bg-[#2563EB] hover:bg-[#1D4ED8]"
              disabled={!resolution.trim()}
              onClick={async () => {
                await run(() => submitResolution(ticket.id, resolution.trim()))
                setHandleOpen(false)
              }}
            >
              Submit resolution
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
