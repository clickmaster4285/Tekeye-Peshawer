import type { CSSProperties, RefObject } from "react"
import type { DetectionEvent } from "@/lib/cameras-api"
import { CUSTOMS_LOGO_SRC } from "@/lib/brand"

const NAVY = "#0f2744"
const NAVY_MID = "#1a3a5c"
const GOLD = "#b8860b"
const MUTED = "#5b6b7c"
const LINE = "#d8dee6"
const SOFT = "#f4f7fb"

/** Soft cap so PDF export stays responsive. */
export const DETECTION_PDF_MAX_EVENTS = 500000
/** Class rows per A4 stats page. */
export const DETECTION_PDF_ROWS_PER_PAGE = 22

export type DetectionReportPeriod = "day" | "week" | "month" | "custom"

export type DetectionClassStat = {
  className: string
  count: number
  alerts: number
  avgConfidence: number
  sharePct: number
  cameras: number
}

export type DetectionDateStat = {
  date: string
  count: number
  alerts: number
  classes: number
  avgConfidence: number
  cameras: number
  sharePct: number
}

export type DetectionPdfPage = {
  key: string
  section: "class" | "date"
  pageIndex: number
  pageCount: number
  sectionPageIndex: number
  sectionPageCount: number
  totalDetections: number
  totalClasses: number
  totalDays: number
  totalAlerts: number
  avgConfidence: number
  rows: DetectionClassStat[]
  dateRows: DetectionDateStat[]
  isFirstPage: boolean
  isLastPage: boolean
}

function absoluteAssetUrl(path: string): string {
  if (typeof window === "undefined") return path
  if (path.startsWith("http") || path.startsWith("data:")) return path
  return `${window.location.origin}${path.startsWith("/") ? "" : "/"}${path}`
}

function eventDateKey(iso: string): string {
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return (iso || "").slice(0, 10)
    const y = d.getFullYear()
    const m = String(d.getMonth() + 1).padStart(2, "0")
    const day = String(d.getDate()).padStart(2, "0")
    return `${y}-${m}-${day}`
  } catch {
    return (iso || "").slice(0, 10)
  }
}

function formatDateLabel(ymd: string): string {
  try {
    const d = new Date(`${ymd}T12:00:00`)
    if (Number.isNaN(d.getTime())) return ymd
    return d.toLocaleDateString("en-GB", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    })
  } catch {
    return ymd
  }
}

function cameraLabel(ev: DetectionEvent): string {
  return (
    ev.camera_name?.trim() ||
    ev.name?.trim() ||
    ev.camera_code?.trim() ||
    (ev.camera != null ? `Camera ${ev.camera}` : "—")
  )
}

function classKey(name: string): string {
  return (name || "unknown").trim().toLowerCase() || "unknown"
}

function displayClassName(name: string): string {
  const raw = (name || "unknown").trim() || "unknown"
  const key = raw.toLowerCase().replace(/[_\s-]+/g, "")
  // Report-only labels (DB / UI still use raw class names)
  if (key === "bus") return "BUS(Hiace)"
  if (key === "truck") return "Truck(Mazda)"
  return raw.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
}

/** Monday-start ISO week for a YYYY-MM-DD date. */
export function getWeekRange(dateStr: string): { start: string; end: string } {
  const d = new Date(`${dateStr}T12:00:00`)
  const day = d.getDay()
  const diffToMon = day === 0 ? -6 : 1 - day
  const start = new Date(d)
  start.setDate(d.getDate() + diffToMon)
  const end = new Date(start)
  end.setDate(start.getDate() + 6)
  const iso = (x: Date) => x.toISOString().slice(0, 10)
  return { start: iso(start), end: iso(end) }
}

export function getMonthRange(dateStr: string): { start: string; end: string } {
  const [y, m] = dateStr.split("-").map(Number)
  const start = `${y}-${String(m).padStart(2, "0")}-01`
  const lastDay = new Date(y, m, 0).getDate()
  const end = `${y}-${String(m).padStart(2, "0")}-${String(lastDay).padStart(2, "0")}`
  return { start, end }
}

export const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
] as const

/** Inclusive date range for a calendar month (1–12). */
export function monthYearRange(year: number, month: number): { date_from: string; date_to: string } {
  const y = Math.max(2000, Math.min(2100, Math.floor(year)))
  const m = Math.max(1, Math.min(12, Math.floor(month)))
  const start = `${y}-${String(m).padStart(2, "0")}-01`
  const lastDay = new Date(y, m, 0).getDate()
  const end = `${y}-${String(m).padStart(2, "0")}-${String(lastDay).padStart(2, "0")}`
  return { date_from: start, date_to: end }
}

export function monthYearLabel(year: number, month: number): string {
  const name = MONTH_NAMES[Math.max(0, Math.min(11, month - 1))] || "Month"
  return `Monthly report — ${name} ${year}`
}

/** Recent years for the month-wise PDF picker (newest first). */
export function reportYearOptions(span = 6): number[] {
  const current = new Date().getFullYear()
  return Array.from({ length: span }, (_, i) => current - i)
}

export function periodDateRange(
  period: DetectionReportPeriod,
  anchorDate: string,
  customFrom?: string,
  customTo?: string
): { date_from: string; date_to: string } {
  if (period === "custom") {
    return {
      date_from: (customFrom || anchorDate || "").slice(0, 10),
      date_to: (customTo || customFrom || anchorDate || "").slice(0, 10),
    }
  }
  if (!anchorDate) {
    const today = new Date().toISOString().slice(0, 10)
    return { date_from: today, date_to: today }
  }
  if (period === "day") return { date_from: anchorDate, date_to: anchorDate }
  if (period === "week") {
    const { start, end } = getWeekRange(anchorDate)
    return { date_from: start, date_to: end }
  }
  const { start, end } = getMonthRange(anchorDate)
  return { date_from: start, date_to: end }
}

export function detectionPeriodLabel(
  period: DetectionReportPeriod,
  anchorDate: string,
  customFrom?: string,
  customTo?: string
): string {
  const { date_from, date_to } = periodDateRange(period, anchorDate, customFrom, customTo)
  if (!date_from) return "Detection report"
  if (date_from === date_to) return `Daily report — ${date_from}`
  if (period === "week") return `Weekly report — ${date_from} to ${date_to}`
  if (period === "month") {
    const [y, m] = date_from.split("-").map(Number)
    if (y && m) return monthYearLabel(y, m)
    return `Monthly report — ${date_from.slice(0, 7)}`
  }
  return `Custom range — ${date_from} to ${date_to}`
}

/** Build class-wise + date-wise stats pages (no images). */
export function buildDetectionPdfPages(
  events: DetectionEvent[],
  opts?: { classFilter?: string; rowsPerPage?: number }
): DetectionPdfPage[] {
  const perPage = Math.max(8, opts?.rowsPerPage ?? DETECTION_PDF_ROWS_PER_PAGE)
  const filter = (opts?.classFilter || "").trim().toLowerCase()

  type ClassAgg = {
    className: string
    count: number
    alerts: number
    confSum: number
    cameras: Set<string>
  }
  type DateAgg = {
    date: string
    count: number
    alerts: number
    confSum: number
    classes: Set<string>
    cameras: Set<string>
  }

  const byClass = new Map<string, ClassAgg>()
  const byDate = new Map<string, DateAgg>()

  for (const ev of events) {
    const key = classKey(ev.class_name || ev.label || "unknown")
    if (filter && key !== filter) continue

    let classAgg = byClass.get(key)
    if (!classAgg) {
      classAgg = {
        className: displayClassName(ev.class_name || key),
        count: 0,
        alerts: 0,
        confSum: 0,
        cameras: new Set(),
      }
      byClass.set(key, classAgg)
    }
    classAgg.count += 1
    if (ev.is_alert) classAgg.alerts += 1
    classAgg.confSum += Number(ev.confidence) || 0
    classAgg.cameras.add(cameraLabel(ev))

    const dateKey = eventDateKey(ev.created_at)
    let dateAgg = byDate.get(dateKey)
    if (!dateAgg) {
      dateAgg = {
        date: dateKey,
        count: 0,
        alerts: 0,
        confSum: 0,
        classes: new Set(),
        cameras: new Set(),
      }
      byDate.set(dateKey, dateAgg)
    }
    dateAgg.count += 1
    if (ev.is_alert) dateAgg.alerts += 1
    dateAgg.confSum += Number(ev.confidence) || 0
    dateAgg.classes.add(key)
    dateAgg.cameras.add(cameraLabel(ev))
  }

  const totalDetections = Array.from(byClass.values()).reduce((s, a) => s + a.count, 0)
  const totalAlerts = Array.from(byClass.values()).reduce((s, a) => s + a.alerts, 0)
  const confSumAll = Array.from(byClass.values()).reduce((s, a) => s + a.confSum, 0)
  const avgConfidence = totalDetections > 0 ? confSumAll / totalDetections : 0

  const classStats: DetectionClassStat[] = Array.from(byClass.values())
    .map((a) => ({
      className: a.className,
      count: a.count,
      alerts: a.alerts,
      avgConfidence: a.count > 0 ? a.confSum / a.count : 0,
      sharePct: totalDetections > 0 ? (a.count / totalDetections) * 100 : 0,
      cameras: a.cameras.size,
    }))
    .sort((a, b) => b.count - a.count || a.className.localeCompare(b.className))

  const dateStats: DetectionDateStat[] = Array.from(byDate.values())
    .map((a) => ({
      date: a.date,
      count: a.count,
      alerts: a.alerts,
      classes: a.classes.size,
      avgConfidence: a.count > 0 ? a.confSum / a.count : 0,
      cameras: a.cameras.size,
      sharePct: totalDetections > 0 ? (a.count / totalDetections) * 100 : 0,
    }))
    .sort((a, b) => a.date.localeCompare(b.date))

  if (classStats.length === 0 && dateStats.length === 0) return []

  const classChunks: DetectionClassStat[][] = []
  for (let i = 0; i < classStats.length; i += perPage) {
    classChunks.push(classStats.slice(i, i + perPage))
  }
  if (classChunks.length === 0) classChunks.push([])

  const dateChunks: DetectionDateStat[][] = []
  for (let i = 0; i < dateStats.length; i += perPage) {
    dateChunks.push(dateStats.slice(i, i + perPage))
  }
  if (dateChunks.length === 0 && dateStats.length === 0) {
    // still add an empty date page only if we have class data? Skip empty date section.
  }

  const pages: DetectionPdfPage[] = []
  const classPageCount = classChunks.length
  const datePageCount = dateChunks.length
  const pageCount = classPageCount + datePageCount

  classChunks.forEach((rows, sectionPageIndex) => {
    const pageIndex = sectionPageIndex
    pages.push({
      key: `class-p${sectionPageIndex + 1}`,
      section: "class",
      pageIndex,
      pageCount,
      sectionPageIndex,
      sectionPageCount: classPageCount,
      totalDetections,
      totalClasses: classStats.length,
      totalDays: dateStats.length,
      totalAlerts,
      avgConfidence,
      rows,
      dateRows: [],
      isFirstPage: pageIndex === 0,
      isLastPage: pageIndex === pageCount - 1,
    })
  })

  dateChunks.forEach((dateRows, sectionPageIndex) => {
    const pageIndex = classPageCount + sectionPageIndex
    pages.push({
      key: `date-p${sectionPageIndex + 1}`,
      section: "date",
      pageIndex,
      pageCount,
      sectionPageIndex,
      sectionPageCount: datePageCount,
      totalDetections,
      totalClasses: classStats.length,
      totalDays: dateStats.length,
      totalAlerts,
      avgConfidence,
      rows: [],
      dateRows,
      isFirstPage: pageIndex === 0,
      isLastPage: pageIndex === pageCount - 1,
    })
  })

  return pages
}

type DetectionPdfReportProps = {
  pages: DetectionPdfPage[]
  periodLabel: string
  filterSummary?: string
  reportRef: RefObject<HTMLDivElement | null>
}

export function DetectionPdfReport({
  pages,
  periodLabel,
  filterSummary,
  reportRef,
}: DetectionPdfReportProps) {
  const generatedAt = new Date().toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
  const logoSrc = absoluteAssetUrl(CUSTOMS_LOGO_SRC)

  return (
    <div
      ref={reportRef}
      style={{
        position: "fixed",
        left: "-10000px",
        top: 0,
        width: "210mm",
        background: "#fff",
        color: "#142033",
        fontFamily: "Georgia, 'Times New Roman', Times, serif",
      }}
      aria-hidden
    >
      {pages.map((page, pageIndex) => (
        <div
          key={page.key}
          className="det-pdf-page"
          data-pdf-page="1"
          style={{
            width: "210mm",
            height: "297mm",
            padding: "0",
            margin: "0",
            boxSizing: "border-box",
            background: "#fff",
            overflow: "hidden",
            position: "relative",
            display: "flex",
            flexDirection: "column",
          }}
        >
          <div
            style={{
              background: NAVY,
              color: "#fff",
              padding: "8mm 12mm 7mm",
              flexShrink: 0,
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: "14px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "12px", minWidth: 0 }}>
                <div
                  style={{
                    width: "16mm",
                    height: "16mm",
                    background: "#fff",
                    borderRadius: "3px",
                    padding: "2mm",
                    boxSizing: "border-box",
                    flexShrink: 0,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  <img
                    src={logoSrc}
                    alt="CIIS"
                    crossOrigin="anonymous"
                    style={{
                      width: "100%",
                      height: "100%",
                      objectFit: "contain",
                      display: "block",
                    }}
                  />
                </div>
                <div style={{ minWidth: 0 }}>
                  <p
                    style={{
                      margin: 0,
                      fontSize: "11px",
                      letterSpacing: "0.22em",
                      textTransform: "uppercase",
                      color: GOLD,
                      fontFamily: "Arial, Helvetica, sans-serif",
                      fontWeight: 700,
                    }}
                  >
                    CIIS
                  </p>
                  <h1
                    style={{
                      margin: "3px 0 0",
                      fontSize: "20px",
                      fontWeight: 700,
                      letterSpacing: "0.02em",
                      lineHeight: 1.2,
                    }}
                  >
                    Detection Report
                  </h1>
                  <p
                    style={{
                      margin: "4px 0 0",
                      fontSize: "10px",
                      color: "#d7e2f0",
                      fontFamily: "Arial, Helvetica, sans-serif",
                    }}
                  >
                    Camera Analytics · {periodLabel}
                  </p>
                </div>
              </div>
              <div
                style={{
                  textAlign: "right",
                  fontFamily: "Arial, Helvetica, sans-serif",
                  fontSize: "10px",
                  color: "#c5d4e8",
                  lineHeight: 1.5,
                  flexShrink: 0,
                }}
              >
                <div>
                  Page {pageIndex + 1} of {pages.length}
                </div>
                <div>Generated {generatedAt}</div>
              </div>
            </div>
            <div
              style={{
                marginTop: "7px",
                height: "3px",
                background: GOLD,
                width: "48px",
              }}
            />
          </div>

          <div
            style={{
              flex: 1,
              padding: "7mm 12mm 8mm",
              boxSizing: "border-box",
              display: "flex",
              flexDirection: "column",
              minHeight: 0,
            }}
          >
            {page.isFirstPage ? (
              <div
                style={{
                  background: SOFT,
                  padding: "4.5mm 5mm",
                  marginBottom: "5mm",
                  boxSizing: "border-box",
                  boxShadow: `inset 0 0 0 1.5px ${LINE}`,
                  flexShrink: 0,
                }}
              >
                <p
                  style={{
                    margin: 0,
                    fontSize: "9px",
                    letterSpacing: "0.14em",
                    textTransform: "uppercase",
                    color: MUTED,
                    fontFamily: "Arial, Helvetica, sans-serif",
                  }}
                >
                  Period summary
                </p>
                <p
                  style={{
                    margin: "3px 0 0",
                    fontSize: "16px",
                    fontWeight: 700,
                    color: NAVY,
                    lineHeight: 1.25,
                  }}
                >
                  {periodLabel}
                </p>
                <div
                  style={{
                    marginTop: "8px",
                    display: "grid",
                    gridTemplateColumns: "1fr 1fr 1fr",
                    gap: "6px 12px",
                    fontFamily: "Arial, Helvetica, sans-serif",
                    fontSize: "10px",
                  }}
                >
                  <MetaItem label="Total detections" value={String(page.totalDetections)} />
                  <MetaItem label="Classes" value={String(page.totalClasses)} />
                  <MetaItem label="Days" value={String(page.totalDays)} />
                  <MetaItem
                    label="Alerts"
                    value={String(page.totalAlerts)}
                    valueColor={page.totalAlerts > 0 ? "#b91c1c" : undefined}
                  />
                  <MetaItem
                    label="Avg confidence"
                    value={`${Math.round(page.avgConfidence * 1000) / 10}%`}
                  />
                  {filterSummary ? (
                    <div style={{ gridColumn: "1 / -1" }}>
                      <MetaItem label="Applied filters" value={filterSummary} />
                    </div>
                  ) : null}
                </div>
              </div>
            ) : null}

            <p
              style={{
                margin: "0 0 6px",
                fontSize: "10px",
                letterSpacing: "0.12em",
                textTransform: "uppercase",
                color: NAVY_MID,
                fontFamily: "Arial, Helvetica, sans-serif",
                fontWeight: 700,
                flexShrink: 0,
              }}
            >
              {page.section === "class" ? "Class-wise statistics" : "Date-wise statistics"}
              {page.sectionPageCount > 1
                ? ` (${page.sectionPageIndex + 1}/${page.sectionPageCount})`
                : ""}
            </p>

            {page.section === "class" ? (
              <table
                style={{
                  width: "100%",
                  borderCollapse: "collapse",
                  fontSize: "10.5px",
                  fontFamily: "Arial, Helvetica, sans-serif",
                }}
              >
                <thead>
                  <tr>
                    <th style={{ ...thStyle, width: "8%" }}>#</th>
                    <th style={{ ...thStyle, width: "32%" }}>Class</th>
                    <th style={{ ...thStyle, textAlign: "right", width: "14%" }}>Count</th>
                    <th style={{ ...thStyle, textAlign: "right", width: "12%" }}>Share</th>
                    <th style={{ ...thStyle, textAlign: "right", width: "12%", color: "#b91c1c" }}>
                      Alerts
                    </th>
                    <th style={{ ...thStyle, textAlign: "right", width: "12%" }}>Avg conf.</th>
                    <th style={{ ...thStyle, textAlign: "right", width: "10%" }}>Cameras</th>
                  </tr>
                </thead>
                <tbody>
                  {page.rows.map((row, i) => {
                    const rank =
                      page.sectionPageIndex * DETECTION_PDF_ROWS_PER_PAGE + i + 1
                    const hasAlerts = row.alerts > 0
                    const rowBg = hasAlerts ? "#fef2f2" : i % 2 === 0 ? "#fff" : SOFT
                    const rowColor = hasAlerts ? "#b91c1c" : "#1a2433"
                    return (
                      <tr key={`${page.key}-${row.className}`} style={{ background: rowBg }}>
                        <td style={{ ...tdStyle, color: rowColor }}>{rank}</td>
                        <td
                          style={{
                            ...tdStyle,
                            fontWeight: 600,
                            color: hasAlerts ? "#b91c1c" : NAVY,
                          }}
                        >
                          {row.className}
                        </td>
                        <td
                          style={{
                            ...tdStyle,
                            textAlign: "right",
                            fontWeight: 600,
                            color: rowColor,
                          }}
                        >
                          {row.count.toLocaleString()}
                        </td>
                        <td style={{ ...tdStyle, textAlign: "right", color: rowColor }}>
                          {row.sharePct.toFixed(1)}%
                        </td>
                        <td
                          style={{
                            ...tdStyle,
                            textAlign: "right",
                            fontWeight: hasAlerts ? 700 : 400,
                            color: rowColor,
                          }}
                        >
                          {row.alerts}
                        </td>
                        <td style={{ ...tdStyle, textAlign: "right", color: rowColor }}>
                          {(Math.round(row.avgConfidence * 1000) / 10).toFixed(1)}%
                        </td>
                        <td style={{ ...tdStyle, textAlign: "right", color: rowColor }}>
                          {row.cameras}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            ) : (
              <table
                style={{
                  width: "100%",
                  borderCollapse: "collapse",
                  fontSize: "10.5px",
                  fontFamily: "Arial, Helvetica, sans-serif",
                }}
              >
                <thead>
                  <tr>
                    <th style={{ ...thStyle, width: "8%" }}>#</th>
                    <th style={{ ...thStyle, width: "28%" }}>Date</th>
                    <th style={{ ...thStyle, textAlign: "right", width: "14%" }}>Count</th>
                    <th style={{ ...thStyle, textAlign: "right", width: "12%" }}>Share</th>
                    <th style={{ ...thStyle, textAlign: "right", width: "12%" }}>Classes</th>
                    <th style={{ ...thStyle, textAlign: "right", width: "12%", color: "#b91c1c" }}>
                      Alerts
                    </th>
                    <th style={{ ...thStyle, textAlign: "right", width: "14%" }}>Avg conf.</th>
                  </tr>
                </thead>
                <tbody>
                  {page.dateRows.map((row, i) => {
                    const rank =
                      page.sectionPageIndex * DETECTION_PDF_ROWS_PER_PAGE + i + 1
                    const hasAlerts = row.alerts > 0
                    const rowBg = hasAlerts ? "#fef2f2" : i % 2 === 0 ? "#fff" : SOFT
                    const rowColor = hasAlerts ? "#b91c1c" : "#1a2433"
                    return (
                      <tr key={`${page.key}-${row.date}`} style={{ background: rowBg }}>
                        <td style={{ ...tdStyle, color: rowColor }}>{rank}</td>
                        <td
                          style={{
                            ...tdStyle,
                            fontWeight: 600,
                            color: hasAlerts ? "#b91c1c" : NAVY,
                          }}
                        >
                          {formatDateLabel(row.date)}
                        </td>
                        <td
                          style={{
                            ...tdStyle,
                            textAlign: "right",
                            fontWeight: 600,
                            color: rowColor,
                          }}
                        >
                          {row.count.toLocaleString()}
                        </td>
                        <td style={{ ...tdStyle, textAlign: "right", color: rowColor }}>
                          {row.sharePct.toFixed(1)}%
                        </td>
                        <td style={{ ...tdStyle, textAlign: "right", color: rowColor }}>
                          {row.classes}
                        </td>
                        <td
                          style={{
                            ...tdStyle,
                            textAlign: "right",
                            fontWeight: hasAlerts ? 700 : 400,
                            color: rowColor,
                          }}
                        >
                          {row.alerts}
                        </td>
                        <td style={{ ...tdStyle, textAlign: "right", color: rowColor }}>
                          {(Math.round(row.avgConfidence * 1000) / 10).toFixed(1)}%
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}

            {page.isLastPage ? (
              <div
                style={{
                  marginTop: "auto",
                  paddingTop: "5mm",
                  borderTop: `2px solid ${NAVY}`,
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  fontFamily: "Arial, Helvetica, sans-serif",
                }}
              >
                <span
                  style={{
                    fontSize: "10px",
                    letterSpacing: "0.1em",
                    textTransform: "uppercase",
                    color: MUTED,
                    fontWeight: 700,
                  }}
                >
                  Grand total
                </span>
                <span style={{ fontSize: "14px", fontWeight: 700, color: NAVY }}>
                  {page.totalDetections.toLocaleString()} detections · {page.totalClasses}{" "}
                  classes · {page.totalDays} days
                </span>
              </div>
            ) : (
              <div style={{ marginTop: "auto" }} />
            )}
          </div>

          <div
            style={{
              flexShrink: 0,
              borderTop: `1px solid ${LINE}`,
              padding: "3.5mm 12mm",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              fontFamily: "Arial, Helvetica, sans-serif",
              fontSize: "8.5px",
              color: MUTED,
              background: SOFT,
            }}
          >
            <span>Confidential — for operations / management use only</span>
            <span style={{ color: NAVY, fontWeight: 600 }}>{periodLabel}</span>
          </div>
        </div>
      ))}
    </div>
  )
}

function MetaItem({
  label,
  value,
  valueColor,
}: {
  label: string
  value: string
  valueColor?: string
}) {
  return (
    <div>
      <div
        style={{
          color: MUTED,
          fontSize: "8.5px",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
        }}
      >
        {label}
      </div>
      <div
        style={{
          marginTop: "1px",
          color: valueColor || "#142033",
          fontWeight: 600,
          fontSize: "11px",
        }}
      >
        {value}
      </div>
    </div>
  )
}

const thStyle: CSSProperties = {
  textAlign: "left",
  padding: "7px 8px",
  borderBottom: `2px solid ${NAVY}`,
  fontWeight: 700,
  color: NAVY,
  background: SOFT,
  fontSize: "9px",
  letterSpacing: "0.06em",
  textTransform: "uppercase",
}

const tdStyle: CSSProperties = {
  padding: "7px 8px",
  borderBottom: `1px solid ${LINE}`,
  color: "#1a2433",
}

function stripThemeStylesFromClone(clonedDoc: Document) {
  clonedDoc.querySelectorAll("style, link[rel='stylesheet']").forEach((el) => el.remove())
  const wipeVars = (el: HTMLElement | null) => {
    if (!el) return
    el.removeAttribute("class")
    el.style.cssText = "background:#ffffff;color:#111111;margin:0;padding:0;"
  }
  wipeVars(clonedDoc.documentElement)
  wipeVars(clonedDoc.body)
}

export async function downloadDetectionPdf(
  element: HTMLElement,
  filename: string
): Promise<void> {
  const pageNodes = Array.from(element.querySelectorAll<HTMLElement>(".det-pdf-page"))
  if (pageNodes.length === 0) throw new Error("No detection pages to export")

  const iframe = document.createElement("iframe")
  iframe.style.cssText =
    "position:fixed;left:-10000px;top:0;width:210mm;height:297mm;border:0;opacity:0;pointer-events:none;"
  document.body.appendChild(iframe)

  try {
    const idoc = iframe.contentDocument
    if (!idoc) throw new Error("Could not create PDF render frame")

    idoc.open()
    idoc.write(
      `<!DOCTYPE html><html><head><meta charset="utf-8"><style>
        html,body{margin:0;padding:0;background:#fff;color:#111;}
        *{box-sizing:border-box;-webkit-print-color-adjust:exact;print-color-adjust:exact;}
      </style></head><body></body></html>`
    )
    idoc.close()

    const html2canvas = (await import("html2canvas")).default
    const { jsPDF } = await import("jspdf")
    const pdf = new jsPDF({ unit: "mm", format: "a4", orientation: "portrait" })
    const pageW = pdf.internal.pageSize.getWidth()
    const pageH = pdf.internal.pageSize.getHeight()

    for (let i = 0; i < pageNodes.length; i++) {
      idoc.body.innerHTML = pageNodes[i].outerHTML
      const clone = idoc.body.firstElementChild as HTMLElement
      clone.style.margin = "0"
      clone.style.position = "static"

      const images = Array.from(clone.querySelectorAll("img"))
      await Promise.all(
        images.map(
          (img) =>
            new Promise<void>((resolve) => {
              if (img.complete) {
                resolve()
                return
              }
              img.onload = () => resolve()
              img.onerror = () => resolve()
            })
        )
      )
      await new Promise((r) => setTimeout(r, 60))

      const canvas = await html2canvas(clone, {
        scale: 2,
        useCORS: true,
        logging: false,
        backgroundColor: "#ffffff",
        width: clone.offsetWidth,
        height: clone.offsetHeight,
        windowWidth: Math.ceil(clone.offsetWidth),
        windowHeight: Math.ceil(clone.offsetHeight),
        onclone: (clonedDoc) => {
          stripThemeStylesFromClone(clonedDoc)
        },
      })

      const imgData = canvas.toDataURL("image/jpeg", 0.92)
      if (i > 0) pdf.addPage()
      pdf.addImage(imgData, "JPEG", 0, 0, pageW, pageH, undefined, "FAST")
    }

    pdf.save(filename.toLowerCase().endsWith(".pdf") ? filename : `${filename}.pdf`)
  } finally {
    iframe.remove()
  }
}
