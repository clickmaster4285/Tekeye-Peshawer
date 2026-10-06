/**
 * Requests & Support API — Request Engine + Support / IT / Developer workflow.
 */
import { API_BASE_URL, getAuthHeaders, getAuthHeadersFormData } from "@/lib/api"

const BASE = `${API_BASE_URL}/api`

export type TicketStatus =
  | "NEW"
  | "TRIAGED"
  | "ASSIGNED"
  | "IN_PROGRESS"
  | "ON_HOLD"
  | "RESOLUTION_SUBMITTED"
  | "SUPPORT_VERIFIED"
  | "PENDING_CLIENT_CONFIRM"
  | "CLOSED"
  | "REOPENED"
  | "CANCELLED"
  | "EXPIRED"

export type Priority = "P1" | "P2" | "P3" | "P4"
export type Department = "IT" | "DEVELOPER" | "UNASSIGNED"

export type SupportCapabilities = {
  role: string
  can_create: boolean
  can_support_triage: boolean
  can_handle_it: boolean
  can_handle_developer: boolean
  can_view_all: boolean
  can_chat?: boolean
  is_requester_only: boolean
  is_admin: boolean
  is_location_admin: boolean
  ticket_validity_hours?: number
}

export type SupportTicket = {
  id: number
  ticket_number: string
  title: string
  description?: string
  status: TicketStatus
  status_label: string
  priority: Priority
  priority_label: string
  category: string
  category_label: string
  department: Department
  department_label: string
  suggested_category?: string
  suggested_category_label?: string
  suggested_priority?: Priority
  suggested_priority_label?: string
  suggested_department?: Department
  suggested_department_label?: string
  site_name: string
  asset_label: string
  camera: number | null
  infra_site: number | null
  infra_device: number | null
  requester: number
  requester_name: string
  assigned_to: number | null
  assigned_to_name: string | null
  is_duplicate: boolean
  duplicate_of: number | null
  resolution_notes?: string
  verification_notes?: string
  client_notes?: string
  sla_response_due: string | null
  sla_resolve_due: string | null
  sla_breached: boolean
  source: string
  created_at: string
  updated_at: string
  expires_at?: string | null
  is_expired?: boolean
  can_chat?: boolean
  validity_remaining_seconds?: number
  assigned_at?: string | null
  resolution_submitted_at?: string | null
  verified_at?: string | null
  client_confirmed_at?: string | null
  closed_at?: string | null
  comments?: SupportComment[]
  events?: SupportEvent[]
  engine?: {
    duplicate_of?: string | null
    duplicate_id?: number | null
    suggested_category?: string
    suggested_priority?: string
    suggested_department?: string
  }
}

export type SupportComment = {
  id: number
  author: number
  author_name: string
  author_role?: string
  body: string
  attachment?: string | null
  attachment_url?: string | null
  attachment_name?: string
  attachment_size?: number | null
  is_internal: boolean
  created_at: string
}

export type TicketChatResponse = {
  ticket_id: number
  ticket_number: string
  status: TicketStatus
  can_chat: boolean
  expires_at: string | null
  validity_remaining_seconds: number
  messages: SupportComment[]
}

export type SupportEvent = {
  id: number
  actor: number | null
  actor_name: string
  event_type: string
  from_status: string
  to_status: string
  message: string
  meta: Record<string, unknown>
  created_at: string
}

export type SupportTrend = {
  pct: number
  sparkline: number[]
}

export type SupportDashboard = {
  capabilities: SupportCapabilities
  counts: Record<string, number | Record<string, number>>
  trends?: Record<string, SupportTrend>
  activity_trend_pct?: number
  sparkline?: number[]
  recent?: SupportTicket[]
}

export type MetaOption = { value: string; label: string }

export type SupportMeta = {
  statuses: MetaOption[]
  priorities: MetaOption[]
  categories: MetaOption[]
  departments: MetaOption[]
  capabilities: SupportCapabilities
}

export type AssignableUser = {
  id: number
  username: string
  full_name: string
  role: string
}

async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      ...getAuthHeaders(),
      ...(init?.headers || {}),
    },
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail || body.error || JSON.stringify(body)
      if (body.force_create_required && body.duplicate_of) {
        detail = `${detail} (existing: ${body.duplicate_of})`
      }
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === "string" ? detail : "Request failed")
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

function qs(params?: Record<string, string | undefined | null>): string {
  if (!params) return ""
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v != null && v !== "") sp.set(k, v)
  }
  const s = sp.toString()
  return s ? `?${s}` : ""
}

export function fetchSupportMe() {
  return apiJson<SupportCapabilities>("/support/me/")
}

export function fetchSupportDashboard() {
  return apiJson<SupportDashboard>("/support/dashboard/")
}

export function fetchSupportMeta() {
  return apiJson<SupportMeta>("/support/tickets/meta/")
}

export function fetchSupportTickets(params?: Record<string, string | undefined | null>) {
  return apiJson<SupportTicket[] | { results: SupportTicket[] }>(
    `/support/tickets/${qs(params)}`
  ).then((data) => (Array.isArray(data) ? data : data.results || []))
}

export function fetchSupportTicket(id: number | string) {
  return apiJson<SupportTicket>(`/support/tickets/${id}/`)
}

export function createSupportRequest(payload: {
  title: string
  description?: string
  camera?: number | null
  infra_site?: number | null
  infra_device?: number | null
  site_name?: string
  asset_label?: string
  preferred_category?: string
  preferred_priority?: string
  contact_phone?: string
  contact_name?: string
  source?: string
  force_create?: boolean
}) {
  return apiJson<SupportTicket>("/support/tickets/", {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export function triageTicket(
  id: number,
  payload: { category: string; priority: string; department: string; notes?: string }
) {
  return apiJson<SupportTicket>(`/support/tickets/${id}/triage/`, {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export function assignTicket(
  id: number,
  payload: { assigned_to?: number | null; department?: string; notes?: string }
) {
  return apiJson<SupportTicket>(`/support/tickets/${id}/assign/`, {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export function startTicket(id: number) {
  return apiJson<SupportTicket>(`/support/tickets/${id}/start/`, { method: "POST", body: "{}" })
}

export function holdTicket(id: number, notes?: string) {
  return apiJson<SupportTicket>(`/support/tickets/${id}/hold/`, {
    method: "POST",
    body: JSON.stringify({ notes: notes || "" }),
  })
}

export function submitResolution(id: number, resolution_notes: string) {
  return apiJson<SupportTicket>(`/support/tickets/${id}/submit-resolution/`, {
    method: "POST",
    body: JSON.stringify({ resolution_notes }),
  })
}

export function verifyTicket(id: number, payload: { approved: boolean; verification_notes?: string }) {
  return apiJson<SupportTicket>(`/support/tickets/${id}/verify/`, {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export function clientConfirmTicket(
  id: number,
  payload: { accepted: boolean; client_notes?: string }
) {
  return apiJson<SupportTicket>(`/support/tickets/${id}/client-confirm/`, {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export function cancelTicket(id: number, notes?: string) {
  return apiJson<SupportTicket>(`/support/tickets/${id}/cancel/`, {
    method: "POST",
    body: JSON.stringify({ notes: notes || "" }),
  })
}

export function addTicketComment(id: number, body: string, is_internal = false) {
  return sendTicketChat(id, body, is_internal)
}

export function fetchTicketChat(id: number | string, after?: number) {
  return apiJson<TicketChatResponse>(
    `/support/tickets/${id}/chat/${qs({ after: after != null ? String(after) : undefined })}`
  )
}

export function sendTicketChat(
  id: number | string,
  body: string,
  is_internal = false,
  file?: File | null
) {
  if (file) {
    const form = new FormData()
    form.append("body", body || "")
    form.append("is_internal", is_internal ? "true" : "false")
    form.append("attachment", file)
    return fetch(`${BASE}/support/tickets/${id}/chat/`, {
      method: "POST",
      headers: getAuthHeadersFormData(),
      body: form,
    }).then(async (res) => {
      if (!res.ok) {
        let detail = res.statusText
        try {
          const b = await res.json()
          detail = b.detail || JSON.stringify(b)
        } catch {
          /* ignore */
        }
        throw new Error(typeof detail === "string" ? detail : "Upload failed")
      }
      return res.json() as Promise<SupportComment>
    })
  }
  return apiJson<SupportComment>(`/support/tickets/${id}/chat/`, {
    method: "POST",
    body: JSON.stringify({ body, is_internal }),
  })
}

export function fetchAssignableUsers(department?: string) {
  return apiJson<AssignableUser[]>(
    `/support/assignable-users/${qs({ department: department || undefined })}`
  )
}

export const STATUS_COLORS: Record<string, string> = {
  NEW: "bg-sky-100 text-sky-800",
  TRIAGED: "bg-indigo-100 text-indigo-800",
  ASSIGNED: "bg-violet-100 text-violet-800",
  IN_PROGRESS: "bg-amber-100 text-amber-900",
  ON_HOLD: "bg-slate-100 text-slate-700",
  RESOLUTION_SUBMITTED: "bg-orange-100 text-orange-900",
  SUPPORT_VERIFIED: "bg-teal-100 text-teal-800",
  PENDING_CLIENT_CONFIRM: "bg-cyan-100 text-cyan-900",
  CLOSED: "bg-emerald-100 text-emerald-800",
  REOPENED: "bg-rose-100 text-rose-800",
  CANCELLED: "bg-gray-100 text-gray-600",
  EXPIRED: "bg-red-100 text-red-800",
}

export const PRIORITY_COLORS: Record<string, string> = {
  P1: "bg-red-100 text-red-800",
  P2: "bg-orange-100 text-orange-800",
  P3: "bg-yellow-100 text-yellow-900",
  P4: "bg-slate-100 text-slate-700",
}
