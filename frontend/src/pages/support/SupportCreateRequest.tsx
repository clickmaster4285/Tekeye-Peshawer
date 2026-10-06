import { useMemo, useRef, useState, type FormEvent, type ReactNode } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link, useNavigate } from "react-router-dom"
import ReactSelect, { type GroupBase, type SingleValue, type StylesConfig } from "react-select"
import {
  Calendar,
  ChevronDown,
  ClipboardList,
  Info,
  Loader2,
  MapPin,
  Phone,
  Send,
  UploadCloud,
  X,
} from "lucide-react"
import { ModulePageLayout } from "@/components/dashboard/module-page-layout"
import { Badge } from "@/components/ui/badge"
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
import { ROUTES, getSupportTicketPath } from "@/routes/config"
import { createSupportRequest, fetchSupportMeta, PRIORITY_COLORS } from "@/lib/support-api"
import { fetchCameras, fetchSites } from "@/lib/cameras-api"
import { getStoredUser } from "@/lib/auth"
import { cn } from "@/lib/utils"

type RequestTypeOption = {
  value: string
  label: string
}

/** TekEye sidebar modules — for Module Access requests */
const TEKEYE_MODULES = [
  "Visitor Management",
  "Warehouse Management",
  "Seizure Management",
  "Human Resource",
  "Armory",
  "Litigation Management",
  "Auction Management",
  "AI Monitoring & Analytics",
  "Requests & Support",
  "System Configuration",
  "Video Recovery",
]

const IMPACT_OPTIONS = [
  { value: "single_device", label: "Single device / camera" },
  { value: "partial_site", label: "Partial site impact" },
  { value: "full_site", label: "Full site down" },
  { value: "multi_site", label: "Multiple sites" },
  { value: "user_access", label: "User access / login issue" },
  { value: "software", label: "Software / application issue" },
  { value: "process", label: "Process / policy" },
  { value: "other", label: "Other" },
]

type FieldFlags = {
  showSite: boolean
  requireSite: boolean
  showCamera: boolean
  requireCamera: boolean
  showOtherAsset: boolean
  showModule: boolean
  requireModule: boolean
  showAccount: boolean
  showPage: boolean
  showEvidenceRange: boolean
  locationTitle: string
  locationSubtitle: string
}

const DEFAULT_FLAGS: FieldFlags = {
  showSite: true,
  requireSite: false,
  showCamera: false,
  requireCamera: false,
  showOtherAsset: false,
  showModule: false,
  requireModule: false,
  showAccount: false,
  showPage: false,
  showEvidenceRange: false,
  locationTitle: "Details for this request",
  locationSubtitle: "Provide context Support needs for this request type.",
}

function flagsForType(type: string): FieldFlags {
  switch (type) {
    case "CAMERA":
    case "NVR":
      return {
        ...DEFAULT_FLAGS,
        showSite: true,
        requireSite: true,
        showCamera: true,
        requireCamera: type === "CAMERA",
        showOtherAsset: true,
        locationTitle: "Location & asset",
        locationSubtitle: "Select the site and related camera or equipment.",
      }
    case "VIDEO_EVIDENCE":
      return {
        ...DEFAULT_FLAGS,
        showSite: true,
        requireSite: true,
        showCamera: true,
        requireCamera: true,
        showEvidenceRange: true,
        locationTitle: "Evidence location",
        locationSubtitle: "Site, camera, and time range for the footage you need.",
      }
    case "NETWORK":
    case "HARDWARE":
    case "SERVER":
    case "INFRASTRUCTURE":
      return {
        ...DEFAULT_FLAGS,
        showSite: true,
        requireSite: true,
        showOtherAsset: true,
        locationTitle: "Location & equipment",
        locationSubtitle: "Select the site and describe the equipment involved.",
      }
    case "MODULE_ACCESS":
      return {
        ...DEFAULT_FLAGS,
        showSite: false,
        showModule: true,
        requireModule: true,
        locationTitle: "Module access",
        locationSubtitle: "Which TekEye module do you need access to?",
      }
    case "ACCESS":
      return {
        ...DEFAULT_FLAGS,
        showSite: false,
        showAccount: true,
        locationTitle: "Account details",
        locationSubtitle: "Tell Support which account or login is affected.",
      }
    case "BUG":
    case "FEATURE":
    case "FRONTEND":
    case "BACKEND":
    case "AI_ML":
    case "API":
    case "DATABASE":
      return {
        ...DEFAULT_FLAGS,
        showSite: false,
        showPage: true,
        locationTitle: "Software details",
        locationSubtitle: "Which module or page is involved?",
      }
    case "REPORT":
    case "TRAINING":
    case "OPS_POLICY":
    case "GENERAL":
    case "OTHER":
    default:
      return {
        ...DEFAULT_FLAGS,
        showSite: true,
        requireSite: false,
        locationTitle: "Optional context",
        locationSubtitle: "Site is optional — add it if the request is location-specific.",
      }
  }
}

const REQUEST_TYPES = [
  { value: "CAMERA", label: "Camera / CCTV", group: "Field / IT" },
  { value: "NVR", label: "NVR / Recording", group: "Field / IT" },
  { value: "NETWORK", label: "Network / PoE", group: "Field / IT" },
  { value: "HARDWARE", label: "Hardware / Power", group: "Field / IT" },
  { value: "SERVER", label: "Server / Infrastructure", group: "Field / IT" },
  { value: "VIDEO_EVIDENCE", label: "Video / Evidence", group: "Evidence & Ops" },
  { value: "MODULE_ACCESS", label: "Module Access", group: "Access & Modules" },
  { value: "ACCESS", label: "Access / Login", group: "Access & Modules" },
  { value: "REPORT", label: "Report / Data Extract", group: "Evidence & Ops" },
  { value: "TRAINING", label: "Training / How-to", group: "Evidence & Ops" },
  { value: "OPS_POLICY", label: "Ops / Admin / Policy", group: "Evidence & Ops" },
  { value: "BUG", label: "Bug / Error", group: "Software" },
  { value: "FEATURE", label: "Feature Request", group: "Software" },
  { value: "FRONTEND", label: "UI / Frontend", group: "Software" },
  { value: "BACKEND", label: "Backend / API", group: "Software" },
  { value: "AI_ML", label: "AI / ML", group: "Software" },
  { value: "GENERAL", label: "General Request", group: "General" },
  { value: "OTHER", label: "Other", group: "General" },
]

const URGENCY_OPTIONS = [
  { value: "P1", label: "Critical (P1)", hint: "Service down / emergency — immediate attention" },
  { value: "P2", label: "High (P2)", hint: "Major impact — needs same-day action" },
  { value: "P3", label: "Medium (P3)", hint: "Degraded service — schedule soon" },
  { value: "P4", label: "Low (P4)", hint: "Minor / enhancement — when available" },
]

const requestTypeSelectStyles: StylesConfig<RequestTypeOption, false, GroupBase<RequestTypeOption>> = {
  container: (base) => ({ ...base, width: "100%" }),
  control: (base, state) => ({
    ...base,
    minHeight: "44px",
    borderRadius: "8px",
    backgroundColor: "#ffffff",
    borderColor: state.isFocused || state.menuIsOpen ? "#155DFC" : "#E5E7EB",
    boxShadow:
      state.isFocused || state.menuIsOpen ? "0 0 0 2px rgba(21, 93, 252, 0.2)" : "none",
    "&:hover": { borderColor: "#155DFC" },
  }),
  valueContainer: (base) => ({ ...base, paddingLeft: "12px" }),
  placeholder: (base) => ({ ...base, color: "#9CA3AF" }),
  singleValue: (base) => ({ ...base, color: "#111827" }),
  menu: (base) => ({ ...base, borderRadius: "8px", overflow: "hidden", zIndex: 30 }),
  menuPortal: (base) => ({ ...base, zIndex: 60 }),
  groupHeading: (base) => ({
    ...base,
    fontSize: "11px",
    fontWeight: 600,
    letterSpacing: "0.04em",
    textTransform: "uppercase",
    color: "#9CA3AF",
    paddingTop: "8px",
  }),
  option: (base, state) => ({
    ...base,
    backgroundColor: state.isSelected
      ? "#155DFC"
      : state.isFocused
        ? "#EBF2FF"
        : "#ffffff",
    color: state.isSelected ? "#ffffff" : "#111827",
    cursor: "pointer",
  }),
}

type SectionTone = "blue" | "green" | "orange" | "indigo"

const SECTION_TONES: Record<
  SectionTone,
  { bar: string; badge: string; badgeText: string; title: string; icon: string; body: string }
> = {
  blue: {
    bar: "bg-[#EBF2FF]",
    badge: "bg-[#155DFC]",
    badgeText: "text-white",
    title: "text-[#155DFC]",
    icon: "text-[#155DFC]",
    body: "bg-white",
  },
  green: {
    bar: "bg-[#ECFDF5]",
    badge: "bg-[#059669]",
    badgeText: "text-white",
    title: "text-[#047857]",
    icon: "text-[#059669]",
    body: "bg-[#F8FFFC]",
  },
  orange: {
    bar: "bg-[#FFF7ED]",
    badge: "bg-[#EA580C]",
    badgeText: "text-white",
    title: "text-[#C2410C]",
    icon: "text-[#EA580C]",
    body: "bg-[#FFFBF7]",
  },
  indigo: {
    bar: "bg-[#EEF2FF]",
    badge: "bg-[#4F46E5]",
    badgeText: "text-white",
    title: "text-[#4338CA]",
    icon: "text-[#4F46E5]",
    body: "bg-[#F8F9FF]",
  },
}

const fieldClass =
  "h-11 w-full rounded-lg border border-[#E5E7EB] bg-white shadow-none focus-visible:border-[#155DFC] focus-visible:ring-[#155DFC]/20"

function FieldHint({ children }: { children: ReactNode }) {
  return <p className="mt-1.5 text-xs leading-relaxed text-[#6B7280]">{children}</p>
}

function FieldLabel({
  htmlFor,
  required,
  children,
}: {
  htmlFor?: string
  required?: boolean
  children: ReactNode
}) {
  return (
    <Label htmlFor={htmlFor} className="mb-1.5 block text-sm font-medium text-[#374151]">
      {children}
      {required ? <span className="ml-0.5 text-red-500">*</span> : null}
    </Label>
  )
}

function FormSection({
  step,
  title,
  subtitle,
  tone,
  open,
  onToggle,
  children,
}: {
  step: number
  title: string
  subtitle?: string
  tone: SectionTone
  open: boolean
  onToggle: () => void
  children: ReactNode
}) {
  const t = SECTION_TONES[tone]
  return (
    <div className="overflow-hidden rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
      <button
        type="button"
        onClick={onToggle}
        className={cn("flex w-full items-center gap-3 px-5 py-4 text-left transition", t.bar)}
      >
        <span
          className={cn(
            "flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold",
            t.badge,
            t.badgeText
          )}
        >
          {step}
        </span>
        <div className="min-w-0 flex-1">
          <p className={cn("text-base font-semibold", t.title)}>{title}</p>
          {subtitle ? <p className="mt-0.5 text-xs text-[#6B7280]">{subtitle}</p> : null}
        </div>
        <ChevronDown
          className={cn("h-5 w-5 shrink-0 transition-transform", t.icon, open && "rotate-180")}
        />
      </button>
      {open ? <div className={cn("space-y-5 px-5 py-5", t.body)}>{children}</div> : null}
    </div>
  )
}

export default function SupportCreateRequest() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const user = getStoredUser()
  const fileRef = useRef<HTMLInputElement>(null)

  const [openSections, setOpenSections] = useState({
    1: true,
    2: true,
    3: true,
    4: true,
  })

  const [title, setTitle] = useState("")
  const [requestType, setRequestType] = useState("")
  const [urgency, setUrgency] = useState("P3")
  const [impact, setImpact] = useState("")
  const [description, setDescription] = useState("")
  const [noticedAt, setNoticedAt] = useState("")
  const [stepsTried, setStepsTried] = useState("")
  const [siteId, setSiteId] = useState("")
  const [cameraId, setCameraId] = useState("")
  const [assetLabel, setAssetLabel] = useState("")
  const [moduleName, setModuleName] = useState("")
  const [accountInfo, setAccountInfo] = useState("")
  const [pageOrModule, setPageOrModule] = useState("")
  const [evidenceFrom, setEvidenceFrom] = useState("")
  const [evidenceTo, setEvidenceTo] = useState("")
  const [attachments, setAttachments] = useState<File[]>([])
  const [contactName, setContactName] = useState(
    user?.full_name || user?.username || ""
  )
  const [contactPhone, setContactPhone] = useState(
    user?.cell_no || user?.phone || user?.office_phone_1 || ""
  )
  const [forceCreate, setForceCreate] = useState(false)
  const [dupWarning, setDupWarning] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)

  const flags = flagsForType(requestType)
  const showTypeFields = Boolean(requestType)

  const sitesQ = useQuery({ queryKey: ["sites"], queryFn: fetchSites })
  const camerasQ = useQuery({
    queryKey: ["cameras", "support-create"],
    queryFn: () => fetchCameras(),
  })
  const metaQ = useQuery({ queryKey: ["support", "meta"], queryFn: fetchSupportMeta })

  const sites = useMemo(() => {
    const rows = sitesQ.data || []
    return [...rows].sort((a, b) => a.name.localeCompare(b.name))
  }, [sitesQ.data])

  const selectedSite = sites.find((s) => String(s.id) === siteId) || null

  const siteCameras = useMemo(() => {
    const rows = camerasQ.data || []
    if (!selectedSite) return []
    return rows
      .filter(
        (c) =>
          c.site_code === selectedSite.code ||
          c.site_name === selectedSite.name ||
          c.location === selectedSite.code
      )
      .sort((a, b) =>
        (a.display_label || a.name).localeCompare(b.display_label || b.name)
      )
  }, [camerasQ.data, selectedSite])

  const selectedCamera =
    cameraId && cameraId !== "__none__"
      ? siteCameras.find((c) => String(c.id) === cameraId) || null
      : null

  const typeLabel = REQUEST_TYPES.find((t) => t.value === requestType)?.label
  const urgencyMeta = URGENCY_OPTIONS.find((u) => u.value === urgency)
  const impactLabel = IMPACT_OPTIONS.find((i) => i.value === impact)?.label

  const onRequestTypeChange = (v: string) => {
    setRequestType(v)
    // Clear type-specific fields when switching
    setCameraId("")
    setAssetLabel("")
    setModuleName("")
    setAccountInfo("")
    setPageOrModule("")
    setEvidenceFrom("")
    setEvidenceTo("")
    const next = flagsForType(v)
    if (!next.showSite) setSiteId("")
    if (!next.requireSite && !next.showCamera) {
      /* keep optional site if still shown */
    }
  }

  const typeFieldsValid = (() => {
    if (!requestType) return false
    if (flags.requireSite && !siteId) return false
    if (flags.requireCamera && (!cameraId || cameraId === "__none__")) return false
    if (flags.requireModule && !moduleName) return false
    if (flags.showAccount && !accountInfo.trim()) return false
    if (flags.showEvidenceRange && (!evidenceFrom || !evidenceTo)) return false
    return true
  })()

  const canSubmit =
    title.trim().length >= 5 &&
    description.trim().length >= 10 &&
    Boolean(requestType) &&
    Boolean(urgency) &&
    Boolean(contactName.trim()) &&
    typeFieldsValid

  const toggleSection = (n: 1 | 2 | 3 | 4) => {
    setOpenSections((s) => ({ ...s, [n]: !s[n] }))
  }

  const addFiles = (list: FileList | null) => {
    if (!list?.length) return
    const next = Array.from(list).filter((f) => f.size <= 15 * 1024 * 1024)
    setAttachments((prev) => [...prev, ...next].slice(0, 5))
  }

  const buildDescription = () => {
    const parts: string[] = [description.trim()]
    if (typeLabel) parts.push(`Request type: ${typeLabel}`)
    if (impactLabel) parts.push(`Impact: ${impactLabel}`)
    if (moduleName) parts.push(`Module requested: ${moduleName}`)
    if (accountInfo.trim()) parts.push(`Account / login: ${accountInfo.trim()}`)
    if (pageOrModule.trim()) parts.push(`Module / page: ${pageOrModule.trim()}`)
    if (evidenceFrom || evidenceTo) {
      parts.push(
        `Evidence time range: ${evidenceFrom || "?"} → ${evidenceTo || "?"}`
      )
    }
    if (noticedAt) parts.push(`First noticed: ${noticedAt}`)
    if (stepsTried.trim()) parts.push(`Steps already tried:\n${stepsTried.trim()}`)
    if (selectedSite) {
      parts.push(
        `Site: ${selectedSite.name}${selectedSite.code ? ` (${selectedSite.code})` : ""}`
      )
    }
    if (selectedCamera) {
      parts.push(
        `Camera: ${selectedCamera.display_label || selectedCamera.name} [ID ${selectedCamera.id}]`
      )
    } else if (assetLabel.trim()) {
      parts.push(`Asset: ${assetLabel.trim()}`)
    }
    if (attachments.length) {
      parts.push(
        `Attached file names (upload via chat after create):\n${attachments
          .map((f) => `• ${f.name}`)
          .join("\n")}`
      )
    }
    if (urgencyMeta) parts.push(`Requester urgency: ${urgencyMeta.label}`)
    return parts.join("\n\n")
  }

  const mutation = useMutation({
    mutationFn: createSupportRequest,
    onSuccess: (ticket) => {
      qc.invalidateQueries({ queryKey: ["support"] })
      navigate(getSupportTicketPath(ticket.id))
    },
    onError: (err: Error) => {
      const msg = err.message || "Failed to create request"
      if (msg.toLowerCase().includes("duplicate") || msg.includes("force_create")) {
        setDupWarning(
          `${msg} Review the existing ticket, or submit again with Force create.`
        )
        setForceCreate(true)
        return
      }
      setFormError(msg)
    },
  })

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    setFormError(null)
    if (!canSubmit) {
      setFormError("Please complete all required fields for this request type.")
      return
    }
    const asset =
      assetLabel.trim() ||
      moduleName ||
      pageOrModule.trim() ||
      (selectedCamera
        ? selectedCamera.display_label || selectedCamera.name || selectedCamera.code
        : "") ||
      accountInfo.trim()

    mutation.mutate({
      title: title.trim(),
      description: buildDescription(),
      site_name: selectedSite?.name || "",
      asset_label: asset,
      camera: flags.showCamera && selectedCamera ? selectedCamera.id : null,
      preferred_category: requestType,
      preferred_priority: urgency,
      contact_name: contactName.trim(),
      contact_phone: contactPhone.trim(),
      source: "portal",
      force_create: forceCreate,
    })
  }

  const typeGroups = useMemo(() => {
    const map = new Map<string, RequestTypeOption[]>()
    for (const t of REQUEST_TYPES) {
      const list = map.get(t.group) || []
      list.push({ value: t.value, label: t.label })
      map.set(t.group, list)
    }
    const extra = (metaQ.data?.categories || [])
      .filter((c) => !REQUEST_TYPES.some((t) => t.value === c.value))
      .map((c) => ({ value: c.value, label: c.label }))
    if (extra.length) {
      map.set("More", [...(map.get("More") || []), ...extra])
    }
    return Array.from(map.entries()).map(([label, options]) => ({ label, options }))
  }, [metaQ.data?.categories])

  const selectedTypeOption =
    typeGroups.flatMap((g) => g.options).find((o) => o.value === requestType) || null

  const needsLocationSection =
    showTypeFields &&
    (flags.showSite ||
      flags.showCamera ||
      flags.showOtherAsset ||
      flags.showModule ||
      flags.showAccount ||
      flags.showPage ||
      flags.showEvidenceRange)

  return (
    <ModulePageLayout
      title="Create Support Request"
      description="Submit any request to TekEye Support — IT, modules, evidence, access, reports, and more."
      breadcrumbs={[
        { label: "Requests & Support", href: ROUTES.SUPPORT_DASHBOARD },
        { label: "Create Request" },
      ]}
    >
      <form
        onSubmit={onSubmit}
        className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_280px]"
      >
        <div className="min-w-0 space-y-4">
          {/* 1 — Request Summary */}
          <FormSection
            step={1}
            title="Request Summary"
            subtitle="Choose the request type first — the form adapts to what you need."
            tone="blue"
            open={openSections[1]}
            onToggle={() => toggleSection(1)}
          >
            <div>
              <FieldLabel required>Request Type</FieldLabel>
              <ReactSelect<RequestTypeOption, false, GroupBase<RequestTypeOption>>
                inputId="support-request-type"
                options={typeGroups}
                value={selectedTypeOption}
                onChange={(opt: SingleValue<RequestTypeOption>) => {
                  onRequestTypeChange(opt?.value || "")
                }}
                placeholder="Search or select what you need help with…"
                isClearable
                isSearchable
                className="react-select-container"
                classNamePrefix="react-select"
                menuPortalTarget={typeof document !== "undefined" ? document.body : undefined}
                menuPosition="fixed"
                styles={requestTypeSelectStyles}
                noOptionsMessage={() => "No matching request types"}
              />
              <FieldHint>
                Camera and site fields only appear when this type needs them.
              </FieldHint>
            </div>

            <div className="grid gap-4 md:grid-cols-[minmax(0,1.85fr)_minmax(0,1fr)]">
              <div className="min-w-0">
                <FieldLabel htmlFor="title" required>
                  Request Title
                </FieldLabel>
                <Input
                  id="title"
                  required
                  maxLength={255}
                  className={fieldClass}
                  placeholder="e.g. Need module access for Armory / Camera 53 offline"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                />
                <FieldHint>Minimum 5 characters. Be specific about what you need.</FieldHint>
              </div>
              <div className="min-w-0">
                <FieldLabel required>Urgency</FieldLabel>
                <Select value={urgency} onValueChange={setUrgency}>
                  <SelectTrigger className={fieldClass}>
                    <SelectValue placeholder="Select urgency" />
                  </SelectTrigger>
                  <SelectContent>
                    {URGENCY_OPTIONS.map((u) => (
                      <SelectItem key={u.value} value={u.value}>
                        {u.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {urgencyMeta ? <FieldHint>{urgencyMeta.hint}</FieldHint> : null}
              </div>
            </div>

            <div>
              <FieldLabel>Business Impact</FieldLabel>
              <Select value={impact} onValueChange={setImpact}>
                <SelectTrigger className={fieldClass}>
                  <SelectValue placeholder="How wide is the impact?" />
                </SelectTrigger>
                <SelectContent>
                  {IMPACT_OPTIONS.map((i) => (
                    <SelectItem key={i.value} value={i.value}>
                      {i.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </FormSection>

          {/* 2 — Type-specific fields */}
          {needsLocationSection && (
            <FormSection
              step={2}
              title={flags.locationTitle}
              subtitle={flags.locationSubtitle}
              tone="green"
              open={openSections[2]}
              onToggle={() => toggleSection(2)}
            >
              {flags.showModule && (
                <div>
                  <FieldLabel required={flags.requireModule}>TekEye Module</FieldLabel>
                  <Select value={moduleName} onValueChange={setModuleName}>
                    <SelectTrigger className={fieldClass}>
                      <SelectValue placeholder="Select module" />
                    </SelectTrigger>
                    <SelectContent>
                      {TEKEYE_MODULES.map((m) => (
                        <SelectItem key={m} value={m}>
                          {m}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FieldHint>Support / Admin will review and grant access if approved.</FieldHint>
                </div>
              )}

              {flags.showAccount && (
                <div>
                  <FieldLabel htmlFor="account" required>
                    Account / username affected
                  </FieldLabel>
                  <Input
                    id="account"
                    className={fieldClass}
                    placeholder="e.g. username, email, or badge ID"
                    value={accountInfo}
                    onChange={(e) => setAccountInfo(e.target.value)}
                  />
                </div>
              )}

              {flags.showPage && (
                <div>
                  <FieldLabel htmlFor="page">Module or page</FieldLabel>
                  <Input
                    id="page"
                    className={fieldClass}
                    placeholder="e.g. Seizure Dashboard, GPS Tracking, Login page"
                    value={pageOrModule}
                    onChange={(e) => setPageOrModule(e.target.value)}
                  />
                </div>
              )}

              {(flags.showSite || flags.showCamera) && (
                <div
                  className={cn(
                    "grid gap-4",
                    flags.showSite && flags.showCamera ? "md:grid-cols-2" : "grid-cols-1"
                  )}
                >
                  {flags.showSite && (
                    <div className="min-w-0">
                      <FieldLabel required={flags.requireSite}>Site</FieldLabel>
                      <Select
                        value={siteId}
                        onValueChange={(v) => {
                          setSiteId(v)
                          setCameraId("")
                          if (!flags.showOtherAsset) setAssetLabel("")
                        }}
                      >
                        <SelectTrigger className={fieldClass}>
                          <SelectValue
                            placeholder={
                              sitesQ.isLoading
                                ? "Loading sites…"
                                : flags.requireSite
                                  ? "Select site"
                                  : "Select site (optional)"
                            }
                          />
                        </SelectTrigger>
                        <SelectContent className="max-h-72">
                          {sites.map((s) => (
                            <SelectItem key={s.id} value={String(s.id)}>
                              {s.name}
                              {s.code ? ` (${s.code})` : ""}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      {!sitesQ.isLoading ? (
                        <FieldHint>{sites.length} sites available</FieldHint>
                      ) : null}
                    </div>
                  )}

                  {flags.showCamera && (
                    <div className="min-w-0">
                      <FieldLabel required={flags.requireCamera}>Camera</FieldLabel>
                      <Select
                        value={cameraId}
                        onValueChange={(v) => {
                          setCameraId(v)
                          if (v && v !== "__none__") {
                            const cam = siteCameras.find((c) => String(c.id) === v)
                            if (cam) {
                              setAssetLabel(cam.display_label || cam.name || cam.code)
                            }
                          }
                        }}
                        disabled={flags.showSite && !selectedSite}
                      >
                        <SelectTrigger className={fieldClass}>
                          <SelectValue
                            placeholder={
                              flags.showSite && !selectedSite
                                ? "Select a site first"
                                : camerasQ.isLoading
                                  ? "Loading cameras…"
                                  : flags.requireCamera
                                    ? "Select camera"
                                    : "Select camera (optional)"
                            }
                          />
                        </SelectTrigger>
                        <SelectContent className="max-h-72">
                          {!flags.requireCamera && (
                            <SelectItem value="__none__">Not a specific camera</SelectItem>
                          )}
                          {siteCameras.map((c) => (
                            <SelectItem key={c.id} value={String(c.id)}>
                              {c.display_label || `${c.name} · Ch ${c.channel}`}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  )}
                </div>
              )}

              {flags.showEvidenceRange && (
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="min-w-0">
                    <FieldLabel htmlFor="evFrom" required>
                      Footage from
                    </FieldLabel>
                    <Input
                      id="evFrom"
                      type="datetime-local"
                      className={fieldClass}
                      value={evidenceFrom}
                      onChange={(e) => setEvidenceFrom(e.target.value)}
                    />
                  </div>
                  <div className="min-w-0">
                    <FieldLabel htmlFor="evTo" required>
                      Footage to
                    </FieldLabel>
                    <Input
                      id="evTo"
                      type="datetime-local"
                      className={fieldClass}
                      value={evidenceTo}
                      onChange={(e) => setEvidenceTo(e.target.value)}
                    />
                  </div>
                </div>
              )}

              {flags.showOtherAsset && (
                <div>
                  <FieldLabel htmlFor="asset">Other asset / equipment</FieldLabel>
                  <Input
                    id="asset"
                    className={fieldClass}
                    placeholder="e.g. NVR-02, UPS Main, Switch Rack A"
                    value={assetLabel}
                    onChange={(e) => setAssetLabel(e.target.value)}
                    disabled={flags.showSite && !selectedSite}
                  />
                  <FieldHint>
                    Use this when the issue is not a specific camera (NVR, UPS, network…).
                  </FieldHint>
                </div>
              )}
            </FormSection>
          )}

          {!requestType && (
            <div className="rounded-xl border border-dashed border-[#BFDBFE] bg-[#F8FBFF] px-5 py-8 text-center text-sm text-[#1E40AF]">
              Select a <strong>Request Type</strong> above to show the right fields for your request.
            </div>
          )}

          {/* 3 — Issue details */}
          <FormSection
            step={needsLocationSection ? 3 : 2}
            title="Issue details"
            subtitle="Describe what you need and anything already tried."
            tone="orange"
            open={openSections[3]}
            onToggle={() => toggleSection(3)}
          >
            <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
              <div className="min-w-0">
                <FieldLabel htmlFor="description" required>
                  Detailed description
                </FieldLabel>
                <Textarea
                  id="description"
                  required
                  rows={9}
                  className="min-h-[220px] w-full resize-y rounded-lg border border-[#E5E7EB] bg-white focus-visible:border-[#155DFC] focus-visible:ring-[#155DFC]/20"
                  placeholder={
                    requestType === "VIDEO_EVIDENCE"
                      ? "Why is the footage needed?\n• Case / incident reference\n• What should be visible\n• Preferred export format"
                      : requestType === "MODULE_ACCESS"
                        ? "Why do you need this module?\n• Your role / duty\n• Who approved (if any)"
                        : "Describe clearly:\n• What do you need?\n• What is not working?\n• When did it start?\n• Who is affected?"
                  }
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
                <FieldHint>Minimum 10 characters.</FieldHint>
              </div>

              <div className="min-w-0">
                <FieldLabel>Attach files</FieldLabel>
                <button
                  type="button"
                  onClick={() => fileRef.current?.click()}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => {
                    e.preventDefault()
                    addFiles(e.dataTransfer.files)
                  }}
                  className="flex min-h-[220px] w-full flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-[#93C5FD] bg-[#F0F7FF] px-4 py-6 text-center transition hover:border-[#155DFC] hover:bg-[#EBF2FF]"
                >
                  <UploadCloud className="h-9 w-9 text-[#155DFC]" />
                  <span className="text-sm font-semibold text-[#155DFC]">Attach files</span>
                  <span className="max-w-[200px] text-xs leading-relaxed text-[#6B7280]">
                    Drag & drop or click (images, logs, screenshots)
                  </span>
                </button>
                <input
                  ref={fileRef}
                  type="file"
                  multiple
                  className="hidden"
                  onChange={(e) => {
                    addFiles(e.target.files)
                    e.target.value = ""
                  }}
                />
                {attachments.length > 0 ? (
                  <ul className="mt-2 space-y-1">
                    {attachments.map((f) => (
                      <li
                        key={`${f.name}-${f.size}`}
                        className="flex items-center gap-2 rounded-lg bg-white px-2 py-1.5 text-xs ring-1 ring-[#E5E7EB]"
                      >
                        <span className="min-w-0 flex-1 truncate">{f.name}</span>
                        <button
                          type="button"
                          className="text-[#6B7280] hover:text-red-600"
                          onClick={() =>
                            setAttachments((prev) => prev.filter((x) => x !== f))
                          }
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            </div>

            {!flags.showEvidenceRange && (
              <div className="grid gap-4 md:grid-cols-2">
                <div className="min-w-0">
                  <FieldLabel htmlFor="noticed">First noticed</FieldLabel>
                  <div className="relative">
                    <Input
                      id="noticed"
                      type="datetime-local"
                      className={cn(fieldClass, "pr-10")}
                      value={noticedAt}
                      onChange={(e) => setNoticedAt(e.target.value)}
                    />
                    <Calendar className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#9CA3AF]" />
                  </div>
                </div>
                <div className="min-w-0">
                  <FieldLabel htmlFor="steps">Steps already tried</FieldLabel>
                  <Input
                    id="steps"
                    className={fieldClass}
                    placeholder="e.g. Rebooted device, cleared cache…"
                    value={stepsTried}
                    onChange={(e) => setStepsTried(e.target.value)}
                  />
                </div>
              </div>
            )}
          </FormSection>

          {/* 4 — Contact */}
          <FormSection
            step={needsLocationSection ? 4 : 3}
            title="Contact for follow-up"
            subtitle="Support may call or message you while working on this request."
            tone="indigo"
            open={openSections[4]}
            onToggle={() => toggleSection(4)}
          >
            <div className="grid gap-4 md:grid-cols-2">
              <div className="min-w-0">
                <FieldLabel htmlFor="contactName" required>
                  Contact name
                </FieldLabel>
                <Input
                  id="contactName"
                  className={fieldClass}
                  value={contactName}
                  onChange={(e) => setContactName(e.target.value)}
                  placeholder="Full name"
                />
                {(user?.role || user?.username) && (
                  <FieldHint>
                    Logged in as {user?.full_name || user?.username}
                    {user?.role ? ` · ${String(user.role).replace(/_/g, " ")}` : ""}
                  </FieldHint>
                )}
              </div>
              <div className="min-w-0">
                <FieldLabel htmlFor="contactPhone">Phone / WhatsApp</FieldLabel>
                <div className="relative">
                  <Phone className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#9CA3AF]" />
                  <Input
                    id="contactPhone"
                    className={cn(fieldClass, "pl-9")}
                    value={contactPhone}
                    onChange={(e) => setContactPhone(e.target.value)}
                    placeholder="03XX-XXXXXXX"
                  />
                </div>
              </div>
            </div>
          </FormSection>

          {(dupWarning || formError) && (
            <div
              className={cn(
                "rounded-xl border px-4 py-3 text-sm",
                dupWarning
                  ? "border-amber-200 bg-amber-50 text-amber-950"
                  : "border-red-200 bg-red-50 text-red-800"
              )}
            >
              {dupWarning || formError}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-3 border-t border-[#E5E7EB] pt-5 pb-2">
            <Button
              type="button"
              variant="ghost"
              className="h-11 px-5 text-[#4B5563] hover:bg-[#F3F4F6] hover:text-[#111827]"
              asChild
            >
              <Link to={`${ROUTES.SUPPORT_ALL}?queue=my_requests`}>Cancel</Link>
            </Button>
            <Button
              type="submit"
              className="h-11 bg-[#155DFC] px-6 hover:bg-[#1248c9]"
              disabled={mutation.isPending || !canSubmit}
            >
              {mutation.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Submitting…
                </>
              ) : (
                <>
                  <Send className="mr-2 h-4 w-4" />
                  {forceCreate ? "Force create request" : "Submit to Support"}
                </>
              )}
            </Button>
            <span className="text-xs text-[#6B7280]">
              Complete required fields marked with <span className="text-red-500">*</span>
            </span>
          </div>
        </div>

        <aside className="space-y-4 xl:sticky xl:top-4 xl:self-start">
          <div className="rounded-xl border border-[#BFDBFE] bg-[#EBF2FF] p-5 shadow-sm">
            <div className="mb-4 flex items-center gap-2.5">
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-[#155DFC] text-white">
                <Info className="h-4 w-4" />
              </span>
              <h3 className="text-sm font-semibold text-[#1E3A8A]">What happens next</h3>
            </div>
            <ol className="space-y-3.5 text-sm leading-relaxed text-[#1E40AF]">
              <li className="flex gap-2.5">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white text-[11px] font-semibold text-[#155DFC] shadow-sm">
                  1
                </span>
                <span>Support receives your request and classifies it.</span>
              </li>
              <li className="flex gap-2.5">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white text-[11px] font-semibold text-[#155DFC] shadow-sm">
                  2
                </span>
                <span>Support handles it, or assigns IT / Developer / Ops / Admin as needed.</span>
              </li>
              <li className="flex gap-2.5">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white text-[11px] font-semibold text-[#155DFC] shadow-sm">
                  3
                </span>
                <span>You confirm when resolved — then the ticket closes.</span>
              </li>
            </ol>
          </div>

          <div className="rounded-xl border border-[#E5E7EB] bg-white p-5 shadow-sm">
            <div className="mb-1 flex items-center gap-2">
              <ClipboardList className="h-4 w-4 text-[#155DFC]" />
              <h3 className="text-sm font-semibold text-[#111827]">Request preview</h3>
            </div>
            <p className="mb-4 text-xs text-[#9CA3AF]">Review before submitting</p>
            <dl className="space-y-3.5 text-sm">
              <div>
                <dt className="text-[11px] font-medium uppercase tracking-wide text-[#9CA3AF]">
                  Title
                </dt>
                <dd className="mt-1 font-medium text-[#111827] break-words">
                  {title.trim() || "—"}
                </dd>
              </div>
              <div>
                <dt className="text-[11px] font-medium uppercase tracking-wide text-[#9CA3AF]">
                  Type
                </dt>
                <dd className="mt-1.5">
                  {requestType ? (
                    <Badge
                      variant="secondary"
                      className="bg-[#EBF2FF] font-normal text-[#155DFC]"
                    >
                      {typeLabel}
                    </Badge>
                  ) : (
                    <Badge
                      variant="secondary"
                      className="bg-[#F3F4F6] font-normal text-[#6B7280]"
                    >
                      Type not set
                    </Badge>
                  )}
                </dd>
              </div>
              {flags.showSite && (
                <div>
                  <dt className="text-[11px] font-medium uppercase tracking-wide text-[#9CA3AF]">
                    Site
                  </dt>
                  <dd className="mt-1 flex items-center gap-1.5 text-[#374151]">
                    <MapPin className="h-3.5 w-3.5 shrink-0 text-[#9CA3AF]" />
                    {selectedSite?.name || "—"}
                  </dd>
                </div>
              )}
              {flags.showModule && (
                <div>
                  <dt className="text-[11px] font-medium uppercase tracking-wide text-[#9CA3AF]">
                    Module
                  </dt>
                  <dd className="mt-1 text-[#374151]">{moduleName || "—"}</dd>
                </div>
              )}
              <div>
                <dt className="text-[11px] font-medium uppercase tracking-wide text-[#9CA3AF]">
                  Urgency
                </dt>
                <dd className="mt-1.5">
                  <Badge
                    className={cn(
                      "font-normal",
                      PRIORITY_COLORS[urgency] || "bg-orange-100 text-orange-800"
                    )}
                    variant="secondary"
                  >
                    {urgencyMeta?.label || "Medium (P3)"}
                  </Badge>
                </dd>
              </div>
            </dl>
          </div>
        </aside>
      </form>
    </ModulePageLayout>
  )
}
