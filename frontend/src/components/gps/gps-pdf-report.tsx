import type { CSSProperties, RefObject } from "react"
import { CUSTOMS_LOGO_SRC } from "@/lib/brand"
import type { GpsHistoryPoint, GpsOfficer, GpsReportPeriod } from "@/lib/gps-tracking-api"
import { resolveStaffProfileImageUrl } from "@/lib/staff-api"
import {
  formatClock,
  formatClockWithSeconds,
  formatReportDate,
  gpsPeriodLabel,
  trailDistanceKm,
} from "@/lib/gps-utils"

const NAVY = "#0f2744"
const GOLD = "#b8860b"
const MUTED = "#5b6b7c"
const LINE = "#d8dee6"
const SOFT = "#f4f7fb"
const ROWS_FIRST_PAGE = 18
const ROWS_NEXT_PAGE = 28

function absoluteAssetUrl(path: string): string {
  if (typeof window === "undefined") return path
  if (path.startsWith("http") || path.startsWith("data:")) return path
  return `${window.location.origin}${path.startsWith("/") ? "" : "/"}${path}`
}

function chunkRows<T>(rows: T[], firstSize: number, nextSize: number): T[][] {
  if (rows.length === 0) return [[]]
  const pages: T[][] = []
  pages.push(rows.slice(0, firstSize))
  let i = firstSize
  while (i < rows.length) {
    pages.push(rows.slice(i, i + nextSize))
    i += nextSize
  }
  return pages
}

function formatPointDate(iso: string | null | undefined): string {
  if (!iso) return "—"
  try {
    return new Date(iso).toLocaleDateString("en-GB", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    })
  } catch {
    return "—"
  }
}

type GpsPdfReportProps = {
  officer: GpsOfficer | null
  points: GpsHistoryPoint[]
  period: GpsReportPeriod
  anchorDate: string
  totalCount?: number
  sampled?: boolean
  reportRef: RefObject<HTMLDivElement | null>
}

export function GpsPdfReport({
  officer,
  points,
  period,
  anchorDate,
  totalCount,
  sampled,
  reportRef,
}: GpsPdfReportProps) {
  const name = officer?.name ?? "—"
  const first = points[0]
  const last = points[points.length - 1]
  const distanceKm = trailDistanceKm(points)
  const showDateCol = period !== "day"
  const pages = chunkRows(points, ROWS_FIRST_PAGE, ROWS_NEXT_PAGE)
  const generatedAt = new Date().toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
  const logoSrc = absoluteAssetUrl(CUSTOMS_LOGO_SRC)
  const photoSrc = resolveStaffProfileImageUrl(officer?.profileImage)
  const periodText = gpsPeriodLabel(period, anchorDate)
  const shownLabel =
    sampled && totalCount != null && totalCount > points.length
      ? `${points.length} of ${totalCount} points`
      : `${points.length} shown`

  const thStyle: CSSProperties = {
    textAlign: "left",
    fontSize: "9px",
    fontFamily: "Arial, Helvetica, sans-serif",
    textTransform: "uppercase",
    letterSpacing: "0.06em",
    color: MUTED,
    borderBottom: `1px solid ${LINE}`,
    padding: "5px 4px",
    fontWeight: 700,
  }
  const tdStyle: CSSProperties = {
    fontSize: "10px",
    fontFamily: "Arial, Helvetica, sans-serif",
    borderBottom: `1px solid ${LINE}`,
    padding: "5px 4px",
    verticalAlign: "top",
  }

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
      {pages.map((pageRows, pageIndex) => (
        <div
          key={`gps-pdf-${pageIndex}`}
          className="gps-pdf-page"
          data-pdf-page="1"
          style={{
            width: "210mm",
            height: "297mm",
            padding: 0,
            margin: 0,
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
                    style={{ width: "100%", height: "100%", objectFit: "contain", display: "block" }}
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
                      fontSize: "19px",
                      fontWeight: 700,
                      letterSpacing: "0.02em",
                      lineHeight: 1.2,
                    }}
                  >
                    {name} — GPS Location Report
                  </h1>
                  <p
                    style={{
                      margin: "4px 0 0",
                      fontSize: "10px",
                      color: "#d7e2f0",
                      fontFamily: "Arial, Helvetica, sans-serif",
                    }}
                  >
                    Operations · {periodText}
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
            <div style={{ marginTop: "7px", height: "3px", background: GOLD, width: "48px" }} />
          </div>

          <div
            style={{
              flex: 1,
              padding: "8mm 12mm 10mm",
              boxSizing: "border-box",
              display: "flex",
              flexDirection: "column",
              minHeight: 0,
            }}
          >
            {pageIndex === 0 ? (
              <div
                style={{
                  display: "flex",
                  gap: "8mm",
                  marginBottom: "6mm",
                  padding: "4mm",
                  background: SOFT,
                  border: `1px solid ${LINE}`,
                  borderRadius: "3px",
                }}
              >
                <div
                  style={{
                    width: "28mm",
                    height: "28mm",
                    borderRadius: "3px",
                    overflow: "hidden",
                    background: "#fff",
                    border: `1px solid ${LINE}`,
                    flexShrink: 0,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  {photoSrc ? (
                    <img
                      src={photoSrc}
                      alt=""
                      crossOrigin="anonymous"
                      style={{ width: "100%", height: "100%", objectFit: "cover" }}
                    />
                  ) : (
                    <span
                      style={{
                        fontFamily: "Arial, Helvetica, sans-serif",
                        fontSize: "14px",
                        color: MUTED,
                        fontWeight: 700,
                      }}
                    >
                      {(name || "?").slice(0, 2).toUpperCase()}
                    </span>
                  )}
                </div>
                <div style={{ flex: 1, minWidth: 0, fontFamily: "Arial, Helvetica, sans-serif", fontSize: "11px" }}>
                  <p style={{ margin: 0, fontSize: "14px", fontWeight: 700, color: NAVY }}>{name}</p>
                  <p style={{ margin: "3px 0 0", color: MUTED }}>
                    Employee ID: {officer?.employeeId || "—"}
                  </p>
                  <p style={{ margin: "2px 0 0", color: MUTED }}>Period: {periodText}</p>
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1fr 1fr",
                      gap: "4px 12px",
                      marginTop: "8px",
                    }}
                  >
                    <div>
                      <span style={{ color: MUTED }}>GPS tracking</span>
                      <div style={{ fontWeight: 600 }}>
                        {first && last
                          ? `${formatClock(first.recordedAt)} → ${formatClock(last.recordedAt)}`
                          : "—"}
                      </div>
                    </div>
                    <div>
                      <span style={{ color: MUTED }}>GPS points</span>
                      <div style={{ fontWeight: 600 }}>{shownLabel}</div>
                    </div>
                    <div>
                      <span style={{ color: MUTED }}>Total distance</span>
                      <div style={{ fontWeight: 600 }}>{distanceKm.toFixed(2)} km</div>
                    </div>
                    <div>
                      <span style={{ color: MUTED }}>First / Last</span>
                      <div style={{ fontWeight: 600 }}>
                        {formatClock(first?.recordedAt)} / {formatClock(last?.recordedAt)}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <p
                style={{
                  margin: "0 0 4mm",
                  fontFamily: "Arial, Helvetica, sans-serif",
                  fontSize: "11px",
                  color: MUTED,
                }}
              >
                Continued — {name} · {periodText}
              </p>
            )}

            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  {showDateCol ? <th style={thStyle}>Date</th> : null}
                  <th style={thStyle}>Time</th>
                  <th style={thStyle}>Latitude</th>
                  <th style={thStyle}>Longitude</th>
                  <th style={thStyle}>Accuracy</th>
                  <th style={thStyle}>Status</th>
                </tr>
              </thead>
              <tbody>
                {pageRows.length === 0 ? (
                  <tr>
                    <td
                      colSpan={showDateCol ? 6 : 5}
                      style={{ ...tdStyle, textAlign: "center", color: MUTED, padding: "12mm 4px" }}
                    >
                      No GPS records for this period.
                    </td>
                  </tr>
                ) : (
                  pageRows.map((point, idx) => (
                    <tr key={`${point.recordedAt}-${idx}`}>
                      {showDateCol ? (
                        <td style={tdStyle}>{formatPointDate(point.recordedAt)}</td>
                      ) : null}
                      <td style={{ ...tdStyle, fontWeight: 600 }}>
                        {formatClockWithSeconds(point.recordedAt)}
                      </td>
                      <td style={tdStyle}>{point.latitude.toFixed(5)}</td>
                      <td style={tdStyle}>{point.longitude.toFixed(5)}</td>
                      <td style={tdStyle}>
                        {point.accuracy != null ? `${Math.round(point.accuracy)} m` : "—"}
                      </td>
                      <td style={tdStyle}>{point.status ?? "—"}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>

            {pageIndex === pages.length - 1 && points.length > 0 ? (
              <div
                style={{
                  marginTop: "auto",
                  paddingTop: "5mm",
                  borderTop: `1px solid ${LINE}`,
                  fontFamily: "Arial, Helvetica, sans-serif",
                  fontSize: "10px",
                  color: MUTED,
                }}
              >
                Summary — Employee {name}; GPS points {shownLabel}; Distance {distanceKm.toFixed(2)}{" "}
                km; First {formatReportDate(first?.recordedAt?.slice(0, 10) || anchorDate)}{" "}
                {formatClock(first?.recordedAt)}; Last {formatClock(last?.recordedAt)}.
              </div>
            ) : null}
          </div>
        </div>
      ))}
    </div>
  )
}

export async function downloadGpsPdf(element: HTMLElement, filename: string): Promise<void> {
  const pageNodes = Array.from(element.querySelectorAll<HTMLElement>(".gps-pdf-page"))
  if (pageNodes.length === 0) throw new Error("No GPS pages to export")

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
      })

      const imgData = canvas.toDataURL("image/jpeg", 0.96)
      if (i > 0) pdf.addPage()
      pdf.addImage(imgData, "JPEG", 0, 0, pageW, pageH, undefined, "FAST")
    }

    pdf.save(filename.toLowerCase().endsWith(".pdf") ? filename : `${filename}.pdf`)
  } finally {
    iframe.remove()
  }
}
