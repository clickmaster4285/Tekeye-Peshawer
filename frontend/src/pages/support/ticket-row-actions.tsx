import { type MouseEvent, type ReactNode } from "react"
import { Link } from "react-router-dom"
import {
  Check,
  CheckCircle2,
  Eye,
  MessageSquare,
  Play,
  UserPlus,
  XCircle,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { getSupportTicketPath } from "@/routes/config"
import {
  cancelTicket,
  clientConfirmTicket,
  startTicket,
  verifyTicket,
  type SupportCapabilities,
  type SupportTicket,
} from "@/lib/support-api"
import { cn } from "@/lib/utils"

function ActionIconBtn({
  title,
  onClick,
  to,
  className,
  children,
  disabled,
}: {
  title: string
  onClick?: (e: MouseEvent) => void
  to?: string
  className?: string
  children: ReactNode
  disabled?: boolean
}) {
  if (to) {
    return (
      <Button
        asChild
        size="icon"
        variant="ghost"
        disabled={disabled}
        className={cn("h-8 w-8", className)}
      >
        <Link to={to} title={title} aria-label={title} onClick={(e) => e.stopPropagation()}>
          {children}
        </Link>
      </Button>
    )
  }
  return (
    <Button
      type="button"
      size="icon"
      variant="ghost"
      disabled={disabled}
      title={title}
      aria-label={title}
      className={cn("h-8 w-8", className)}
      onClick={(e) => {
        e.stopPropagation()
        onClick?.(e)
      }}
    >
      {children}
    </Button>
  )
}

export function TicketRowActions({
  ticket,
  caps,
  busy,
  onAction,
}: {
  ticket: SupportTicket
  caps?: SupportCapabilities
  busy: boolean
  onAction: (fn: () => Promise<unknown>) => void
}) {
  const path = getSupportTicketPath(ticket.id)
  const active = !["EXPIRED", "CLOSED", "CANCELLED"].includes(ticket.status)
  const canTriage = Boolean(caps?.can_support_triage)
  const canHandle = Boolean(
    caps?.can_support_triage ||
      (ticket.department === "IT" && caps?.can_handle_it) ||
      (ticket.department === "DEVELOPER" && caps?.can_handle_developer)
  )
  const isRequester = Boolean(caps?.is_requester_only)
  const canChat = Boolean(ticket.can_chat ?? active)

  return (
    <div className="flex items-center justify-end gap-0.5">
      <ActionIconBtn
        title="View details"
        to={path}
        className="text-[#155DFC] hover:bg-[#EBF2FF] hover:text-[#155DFC]"
      >
        <Eye className="h-4 w-4" />
      </ActionIconBtn>

      {canChat && (
        <ActionIconBtn
          title="Reply / chat"
          to={path}
          className="text-sky-600 hover:bg-sky-50 hover:text-sky-700"
        >
          <MessageSquare className="h-4 w-4" />
        </ActionIconBtn>
      )}

      {canTriage && active && (
        <ActionIconBtn
          title="Assign to staff"
          to={path}
          className="text-violet-600 hover:bg-violet-50 hover:text-violet-700"
        >
          <UserPlus className="h-4 w-4" />
        </ActionIconBtn>
      )}

      {canHandle &&
        active &&
        ["ASSIGNED", "TRIAGED", "REOPENED", "ON_HOLD"].includes(ticket.status) && (
          <ActionIconBtn
            title="Start work"
            disabled={busy}
            className="text-emerald-600 hover:bg-emerald-50 hover:text-emerald-700"
            onClick={() => {
              if (window.confirm(`Start work on ${ticket.ticket_number}?`)) {
                onAction(() => startTicket(ticket.id))
              }
            }}
          >
            <Play className="h-4 w-4" />
          </ActionIconBtn>
        )}

      {canTriage && active && ticket.status === "RESOLUTION_SUBMITTED" && (
        <ActionIconBtn
          title="Verify resolution"
          disabled={busy}
          className="text-emerald-600 hover:bg-emerald-50 hover:text-emerald-700"
          onClick={() => {
            if (window.confirm(`Verify resolution for ${ticket.ticket_number}?`)) {
              onAction(() =>
                verifyTicket(ticket.id, {
                  approved: true,
                  verification_notes: "Verified by Support",
                })
              )
            }
          }}
        >
          <Check className="h-4 w-4" />
        </ActionIconBtn>
      )}

      {(isRequester || canTriage) &&
        active &&
        ticket.status === "PENDING_CLIENT_CONFIRM" && (
          <ActionIconBtn
            title="Accept & close"
            disabled={busy}
            className="text-emerald-600 hover:bg-emerald-50 hover:text-emerald-700"
            onClick={() => {
              if (window.confirm(`Accept resolution and close ${ticket.ticket_number}?`)) {
                onAction(() =>
                  clientConfirmTicket(ticket.id, {
                    accepted: true,
                    client_notes: "",
                  })
                )
              }
            }}
          >
            <CheckCircle2 className="h-4 w-4" />
          </ActionIconBtn>
        )}

      {(canTriage || isRequester) && active && (
        <ActionIconBtn
          title="Cancel ticket"
          disabled={busy}
          className="text-red-500 hover:bg-red-50 hover:text-red-600"
          onClick={() => {
            if (window.confirm(`Cancel ${ticket.ticket_number}?`)) {
              onAction(() => cancelTicket(ticket.id, "Cancelled from list"))
            }
          }}
        >
          <XCircle className="h-4 w-4" />
        </ActionIconBtn>
      )}
    </div>
  )
}
