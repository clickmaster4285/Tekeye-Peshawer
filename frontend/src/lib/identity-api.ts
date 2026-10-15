import { API_BASE_URL, getAuthHeaders } from "@/lib/api"

async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...getAuthHeaders(),
      ...(init?.headers || {}),
    },
    cache: "no-store",
  })
  if (response.status === 401) throw new Error("Unauthorized")
  if (response.status === 204) return undefined as T
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    const msg =
      typeof data?.detail === "string"
        ? data.detail
        : typeof data?.error === "string"
          ? data.error
          : `Request failed (${response.status})`
    throw new Error(msg)
  }
  return data as T
}

export type RecognitionMode = "manual" | "assisted" | "automatic"
export type DecisionOutcome = "accepted" | "review" | "unknown"
export type ReviewStatus = "not_required" | "pending" | "approved" | "rejected"

export type ReadinessCheck = {
  value: number
  required?: number
  max?: number
  ok: boolean
}

export type IdentityProfile = {
  staff_id: number
  staff_name: string
  employee_id: string | null
  recognition_mode: RecognitionMode
  mode_changed_by_name: string | null
  mode_changed_at: string | null
  confirmed_matches: number
  rejected_matches: number
  gallery_size: number
  journey_gallery_size: number
  pending_reviews?: number
  automatic_readiness: {
    ready: boolean
    checks: Record<string, ReadinessCheck>
  }
}

export type GalleryEntry = {
  id: number
  source: "enrollment" | "approved_live"
  model_name: string
  quality_score: number | null
  quality: Record<string, unknown>
  camera: number | null
  camera_name: string | null
  image_url: string | null
  origin_decision: number | null
  approved_by_name: string | null
  approved_at: string | null
  is_active: boolean
  created_at: string
}

export const MODEL_LABEL: Record<string, string> = {
  insightface_buffalo_l: "Attendance (InsightFace)",
  sface_2021dec: "Journey (SFace)",
}

export type PolicyGate = {
  gate: string
  passed: boolean | null
  detail: string
}

export type IdentityDecision = {
  id: number
  created_at: string
  source: string
  camera: number | null
  camera_name: string
  track_id: number | null
  journey_person: number | null
  staff: number | null
  staff_name: string | null
  outcome: DecisionOutcome
  confidence: number
  face_similarity: number
  second_best_similarity: number | null
  face_quality: number | null
  model_name: string
  matched_entry: number | null
  matched_entry_image_url: string | null
  factors: Record<string, unknown>
  reason: string
  policy: { action?: string; message?: string; gates?: PolicyGate[] }
  snapshot_url: string | null
  attendance_action: string
  attendance_id: number | null
  review_status: ReviewStatus
  reviewed_by_name: string | null
  reviewed_at: string | null
  review_note: string
  can_add_to_gallery: boolean
  candidate_gallery?: GalleryEntry[]
}

export type DecisionFilters = {
  outcome?: string
  review_status?: string
  source?: string
  staff?: number
  date?: string
  limit?: number
  offset?: number
}

export type ApprovePayload = {
  staff_id?: number
  mark_attendance?: boolean
  add_to_gallery?: boolean
  note?: string
}

export type ApproveResult = {
  attendance: { action: string; record_id: number | null } | null
  gallery: { added: boolean; entry_id: number | null; message: string } | null
  // Journey decision → linked person; cluster decision → every member merged.
  journey: {
    person_code?: string
    person_uuid?: string
    cluster?: string
    merged_persons?: string[]
    journey_person_code?: string | null
    gallery_added?: number
  } | null
  decision: IdentityDecision
}

export type ClusterStatus = "open" | "identified" | "dismissed"

export type UnknownCluster = {
  id: number
  code: string
  status: ClusterStatus
  staff: number | null
  staff_name: string | null
  person_count: number
  observation_count: number
  camera_ids: number[]
  first_seen: string | null
  last_seen: string | null
  member_codes: string[]
  thumbnail_url: string | null
  candidate: {
    decision_id: number
    staff_id: number | null
    staff_name: string | null
    outcome: DecisionOutcome
    face_similarity: number
    confidence: number
    review_status: ReviewStatus
  } | null
  rejected_staff_ids: number[]
  note: string
}

export type UnknownClusterDetail = UnknownCluster & {
  members: Array<{
    code: string
    uuid: string
    person_type: string
    latest_camera: string | null
    latest_seen_at: string | null
    snapshot_url: string | null
    observations: number
  }>
  observations: Array<{
    id: number
    at: string
    camera: string | null
    track_id: number | null
    person_code: string
    has_face: boolean
    snapshot_url: string | null
  }>
}

function qs(params: Record<string, unknown>): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ""
}

export const identityApi = {
  profiles: () =>
    apiJson<{
      results: IdentityProfile[]
      gallery_loaded_staff: Record<string, number>
    }>("/api/identity/profiles/"),
  staff: (staffId: number, includeInactive = false) =>
    apiJson<{ profile: IdentityProfile; gallery: GalleryEntry[] }>(
      `/api/identity/staff/${staffId}/${includeInactive ? "?include_inactive=1" : ""}`
    ),
  setMode: (staffId: number, mode: RecognitionMode) =>
    apiJson<IdentityProfile>(`/api/identity/staff/${staffId}/mode/`, {
      method: "POST",
      body: JSON.stringify({ recognition_mode: mode }),
    }),
  deactivateEntry: (entryId: number) => apiJson<void>(`/api/identity/gallery/${entryId}/`, { method: "DELETE" }),
  reactivateEntry: (entryId: number) =>
    apiJson<GalleryEntry>(`/api/identity/gallery/${entryId}/`, {
      method: "POST",
    }),
  decisions: (filters: DecisionFilters = {}) =>
    apiJson<{
      count: number
      pending_total: number
      results: IdentityDecision[]
    }>(`/api/identity/decisions/${qs(filters)}`),
  decision: (id: number) => apiJson<IdentityDecision>(`/api/identity/decisions/${id}/`),
  approve: (id: number, payload: ApprovePayload) =>
    apiJson<ApproveResult>(`/api/identity/decisions/${id}/approve/`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  reject: (id: number, note = "") =>
    apiJson<IdentityDecision>(`/api/identity/decisions/${id}/reject/`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }),
  clusters: (status: ClusterStatus | "all" = "open") =>
    apiJson<{ count: number; results: UnknownCluster[] }>(`/api/identity/clusters/${qs({ status })}`),
  cluster: (id: number) => apiJson<UnknownClusterDetail>(`/api/identity/clusters/${id}/`),
  assignCluster: (id: number, staffId: number, note = "", addToGallery = true) =>
    apiJson<Omit<ApproveResult, "decision">>(`/api/identity/clusters/${id}/assign/`, {
      method: "POST",
      body: JSON.stringify({ staff_id: staffId, note, add_to_gallery: addToGallery }),
    }),
  dismissCluster: (id: number, note = "") =>
    apiJson<{ status: ClusterStatus }>(`/api/identity/clusters/${id}/dismiss/`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }),
  runClustering: () =>
    apiJson<{ unknown_persons: number; clusters: number; multi_person_clusters: number; candidates_suggested: number }>(
      "/api/identity/clusters/run/",
      { method: "POST" }
    ),
}
