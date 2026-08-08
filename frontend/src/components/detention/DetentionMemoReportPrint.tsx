import { Button } from "@/components/ui/button"
import { Printer } from "lucide-react"
import { getDetentionMemoDetailPath } from "@/routes/config"

type GoodsLineItem = {
  id: string
  qrCodeNumber?: string
  description: string
  pctCode: string
  quantity: string
  unit: string
  condition: string
  assessableValuePkr: string
  identificationRef: string
  itemNotes: string
  perishable?: boolean
}

type DetentionMemoRow = {
  id: string
  caseNo: string
  firNumber?: string
  referenceNumber: string
  dateTimeOccurrence: string
  placeOfOccurrence: string
  dateTimeDetention: string
  placeOfDetention: string
  detentionType: string
  directorate: string
  reasonForDetention: string
  whereDeposited: string
  settlementStatus: string
  verificationStatus: string
  briefFacts?: string
  forwardingOfficerRemarks?: string
  accusedName?: string
  accusedCnic?: string
  accusedAddress?: string
  goodsItems?: GoodsLineItem[]
  seizingOfficerNotes?: string
  examiningOfficerNotes?: string
  detentionNotes?: string
  createdAt: string
  updatedAt?: string
  createdBy?: string
}

interface DetentionMemoReportPrintProps {
  row: DetentionMemoRow
  qrPayload: string
  qrNumber: string
}

function getQrCodeUrl(data: string, size = 120) {
  return `https://api.qrserver.com/v1/create-qr-code/?size=${size}x${size}&data=${encodeURIComponent(data)}`
}

function getGoodsQrPayload(memoId: string, item: GoodsLineItem): string {
  const ref = item.qrCodeNumber || `${memoId}-${item.id}`
  return `${window.location.origin}${getDetentionMemoDetailPath(memoId)}?goodsQr=${encodeURIComponent(ref)}&view=goods`
}

function formatDate(value?: string): string {
  if (!value) return "—"
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleDateString()
}

export default function DetentionMemoReportPrint({ row, qrPayload, qrNumber }: DetentionMemoReportPrintProps) {
  const goodsItems = row.goodsItems ?? []
  const hasGoods = goodsItems.length > 0
  const showPctCode = goodsItems.some((item) => Boolean(item.pctCode?.trim()))
  const showAssessable = goodsItems.some((item) => Boolean(item.assessableValuePkr?.trim()))
  const showPerishable = goodsItems.some((item) => Boolean(item.perishable))
  const showIdentificationRef = goodsItems.some((item) => Boolean(item.identificationRef?.trim()))
  const showNotes = goodsItems.some((item) => Boolean(item.itemNotes?.trim()))

  const hasAdditionalNotes = Boolean(
    row.seizingOfficerNotes || row.examiningOfficerNotes || row.detentionNotes || row.forwardingOfficerRemarks
  )
  const handlePrint = () => window.print()

  // Split across pages for print/PDF:
  // - Page 1: header + key/basic info + memo description
  // - Page 2: goods table + additional remarks + footer
  const showSecondPage = hasGoods || hasAdditionalNotes
  const footerOnPage1 = !showSecondPage

  return (
    <div className="bg-white text-black">
      <style>{`
        :root { color-scheme: light; }

        body { margin: 0; background: white !important; color: #111827 !important; }
        aside, nav, header, .sidebar, .main-nav, .breadcrumbs, [role="navigation"] {
          display: none !important;
        }
        .print-action {
          display: flex;
          justify-content: center;
          padding: 10px 0 6px;
        }
        main, .main-content {
          margin: 0 !important;
          padding: 0 !important;
          width: 100% !important;
          max-width: 100% !important;
        }

        .print-pages {
          width: 100%;
          overflow: visible;
        }

        /* Screen preview: compact flow (no forced empty page area) */
        .print-page {
          width: min(210mm, 100%);
          min-height: auto;
          box-sizing: border-box;
          padding: 12mm;
          margin: 0 auto;
          background: #fff;
        }

        .page-break-after { break-after: auto; page-break-after: auto; }

        .header-section {
          display: grid;
          grid-template-columns: minmax(0, 1fr) 120px;
          gap: 12px;
          align-items: start;
          border-bottom: 2px solid #111827;
          padding-bottom: 8px;
        }
        .header-title {
          font-size: 20px;
          font-weight: 700;
          line-height: 1.2;
        }
        .header-subtitle {
          margin-top: 2px;
          font-size: 12px;
          color: #4b5563;
        }
        .section-title {
          font-size: 12px;
          font-weight: 800;
          text-transform: uppercase;
          letter-spacing: 0.03em;
          margin-bottom: 6px;
          color: #1f2937;
        }

        .box {
          border: 1px solid #e5e7eb;
          border-radius: 6px;
          padding: 10px 12px;
          background: #fff;
        }

        .info-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 6px 16px;
        }

        .info-row {
          display: grid;
          grid-template-columns: 150px minmax(0, 1fr);
          gap: 6px;
          font-size: 10pt;
          line-height: 1.25;
        }
        .info-label { font-weight: 700; color: #374151; }

        .report-section {
          margin-top: 10px;
          page-break-inside: avoid;
          break-inside: avoid;
        }

        .goods-table-wrap { width: 100%; overflow: hidden; }
        .goods-table {
          width: 100%;
          border-collapse: collapse;
          table-layout: fixed;
          font-size: 8.5pt;
        }
        .goods-table th, .goods-table td {
          border: 1px solid #d1d5db;
          padding: 3px 2px;
          text-align: left;
          vertical-align: top;
          word-break: break-word;
          overflow-wrap: anywhere;
        }
        .goods-table th {
          background: #f3f4f6;
          font-weight: 800;
          font-size: 8pt;
          line-height: 1.1;
        }
        .goods-table tbody tr:nth-child(even) { background: #f9fafb; }

        .goods-qr {
          width: 32px;
          height: 32px;
          border: 1px solid #d1d5db;
          border-radius: 4px;
          padding: 2px;
          background: #fff;
          display: block;
        }

        .qr-container { text-align: center; }
        .qr-container img {
          width: 90px;
          height: 90px;
          border: 1px solid #d1d5db;
          border-radius: 6px;
          padding: 3px;
          background: #fff;
        }

        .footer {
          margin-top: 10px;
          border-top: 1px solid #d1d5db;
          padding-top: 6px;
          display: flex;
          justify-content: space-between;
          gap: 12px;
          font-size: 9pt;
          color: #4b5563;
        }

        @media print {
          @page { size: A4; margin: 0; }
          body { margin: 0; }
          .print-action { display: none !important; }
          aside, nav, header, .sidebar, .main-nav, .breadcrumbs, [role="navigation"] {
            display: none !important;
          }
          main, .main-content {
            margin: 0 !important;
            padding: 0 !important;
            width: 100% !important;
            max-width: 100% !important;
          }
          .print-page {
            width: 210mm !important;
            min-height: 297mm !important;
            margin: 0 auto;
          }
          .page-break-after { break-after: page; page-break-after: always; }
          .print-page { margin: 0 auto; }
        }
      `}</style>

      <div className="print-action">
        <Button onClick={handlePrint} variant="outline" className="gap-2">
          <Printer className="h-4 w-4" />
          Print
        </Button>
      </div>

      <div className="print-pages">
        <div className={`print-page ${showSecondPage ? "page-break-after" : ""}`}>
          <div className="header-section">
            <div>
              <div className="section-title" style={{ textTransform: "none", letterSpacing: 0, fontWeight: 800, fontSize: 12 }}>
                Pakistan Customs Authority
              </div>
              <div className="header-title mt-1">Detention Memo Report</div>
              <div className="header-subtitle">Official customs document for goods detention and inventory</div>
            </div>
            <div className="qr-container">
              <img src={getQrCodeUrl(qrPayload, 100)} alt="Memo QR Code" />
              <div style={{ fontSize: 9, fontFamily: "monospace", marginTop: 4, wordBreak: "break-all" }}>
                {qrNumber}
              </div>
            </div>
          </div>

          <div className="report-section box">
            <div className="info-grid">
              <div className="info-row">
                <span className="info-label">Memo Number:</span> {row.caseNo}
              </div>
              <div className="info-row">
                <span className="info-label">Reference Number:</span> {row.referenceNumber || "—"}
              </div>
              <div className="info-row">
                <span className="info-label">Detention Type:</span> {row.detentionType || "—"}
              </div>
              <div className="info-row">
                <span className="info-label">Created By:</span> {row.createdBy || "ASO Portal"}
              </div>
              <div className="info-row">
                <span className="info-label">Created Date:</span> {row.createdAt || "—"}
              </div>
              <div className="info-row" style={{ gridColumn: "1 / -1" }}>
                <span className="info-label">Updated Date:</span> {formatDate(row.updatedAt || row.createdAt)}
              </div>
              <div className="info-row" style={{ gridColumn: "1 / -1" }}>
                <span className="info-label">Verification Status:</span> {row.verificationStatus || "—"}
              </div>
            </div>
          </div>

          <div className="report-section">
            <div className="section-title">Basic Information</div>
            <div className="box">
              <div className="info-grid">
                <div className="info-row">
                  <span className="info-label">Date/Time of Occurrence:</span> {row.dateTimeOccurrence || "—"}
                </div>
                <div className="info-row">
                  <span className="info-label">Place of Occurrence:</span> {row.placeOfOccurrence || "—"}
                </div>
                <div className="info-row">
                  <span className="info-label">Date/Time of Detention:</span> {row.dateTimeDetention || "—"}
                </div>
                <div className="info-row">
                  <span className="info-label">Place of Detention:</span> {row.placeOfDetention || "—"}
                </div>
                <div className="info-row">
                  <span className="info-label">Directorate:</span> {row.directorate || "—"}
                </div>
                <div className="info-row">
                  <span className="info-label">Where Deposited:</span> {row.whereDeposited || "—"}
                </div>
                <div className="info-row">
                  <span className="info-label">Settlement Status:</span> {row.settlementStatus || "—"}
                </div>
                <div className="info-row">
                  <span className="info-label">Reason for Detention:</span> {row.reasonForDetention || "—"}
                </div>
              </div>
            </div>
          </div>

          {row.briefFacts && (
            <div className="report-section">
              <div className="section-title">Memo Description</div>
              <div className="box" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
                <div style={{ fontSize: 10.5, lineHeight: 1.3 }}>{row.briefFacts}</div>
              </div>
            </div>
          )}

          {footerOnPage1 && (
            <div className="footer">
              <span>Generated: {new Date().toLocaleString()}</span>
              <span>Detention Memo System • Pakistan Customs</span>
            </div>
          )}
        </div>

        {showSecondPage && (
          <div className="print-page">
            {hasGoods && (
              <div className="report-section">
                <div className="section-title">Goods Information</div>
                <div className="goods-table-wrap">
                  <table className="goods-table">
                    <thead>
                      <tr>
                        <th style={{ width: "52px" }}>QR</th>
                        <th>Description</th>
                        <th style={{ width: "44px" }}>Qty</th>
                        <th style={{ width: "40px" }}>Unit</th>
                        <th style={{ width: "74px" }}>Condition</th>
                        {showAssessable && <th style={{ width: "80px" }}>Assessable (PKR)</th>}
                        {showPctCode && <th style={{ width: "62px" }}>PCT</th>}
                        {showPerishable && <th style={{ width: "52px" }}>Perish.</th>}
                        {showIdentificationRef && <th style={{ width: "90px" }}>ID/Chassis</th>}
                        {showNotes && <th>Notes</th>}
                      </tr>
                    </thead>
                    <tbody>
                      {goodsItems.map((item) => (
                        <tr key={item.id}>
                          <td>
                            <img
                              className="goods-qr"
                              src={getQrCodeUrl(getGoodsQrPayload(row.id, item), 48)}
                              alt={`Goods QR ${item.qrCodeNumber || item.id}`}
                            />
                            {item.qrCodeNumber && (
                              <div style={{ fontSize: 7.5, marginTop: 2, wordBreak: "break-all", lineHeight: 1.1 }}>
                                {item.qrCodeNumber}
                              </div>
                            )}
                          </td>
                          <td>{item.description || "—"}</td>
                          <td>{item.quantity || "—"}</td>
                          <td>{item.unit || "—"}</td>
                          <td>{item.condition || "—"}</td>
                          {showAssessable && <td>{item.assessableValuePkr || "—"}</td>}
                          {showPctCode && <td>{item.pctCode || "—"}</td>}
                          {showPerishable && <td>{item.perishable ? "Yes" : "No"}</td>}
                          {showIdentificationRef && <td>{item.identificationRef || "—"}</td>}
                          {showNotes && <td>{item.itemNotes || "—"}</td>}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {hasAdditionalNotes && (
              <div className="report-section">
                <div className="section-title">Additional Notes & Remarks</div>
                <div className="box">
                  <div style={{ display: "grid", gap: 10 }}>
                    {row.seizingOfficerNotes && (
                      <div>
                        <div style={{ fontWeight: 800, fontSize: 10, marginBottom: 2 }}>Seizing Officer Notes:</div>
                        <div style={{ fontSize: 10, whiteSpace: "pre-wrap" }}>{row.seizingOfficerNotes}</div>
                      </div>
                    )}
                    {row.examiningOfficerNotes && (
                      <div>
                        <div style={{ fontWeight: 800, fontSize: 10, marginBottom: 2 }}>Examining Officer Notes:</div>
                        <div style={{ fontSize: 10, whiteSpace: "pre-wrap" }}>{row.examiningOfficerNotes}</div>
                      </div>
                    )}
                    {row.detentionNotes && (
                      <div>
                        <div style={{ fontWeight: 800, fontSize: 10, marginBottom: 2 }}>Detention / Customs Notes:</div>
                        <div style={{ fontSize: 10, whiteSpace: "pre-wrap" }}>{row.detentionNotes}</div>
                      </div>
                    )}
                    {row.forwardingOfficerRemarks && (
                      <div>
                        <div style={{ fontWeight: 800, fontSize: 10, marginBottom: 2 }}>Forwarding Officer Remarks:</div>
                        <div style={{ fontSize: 10, whiteSpace: "pre-wrap" }}>{row.forwardingOfficerRemarks}</div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            <div className="footer">
              <span>Generated: {new Date().toLocaleString()}</span>
              <span>Detention Memo System • Pakistan Customs</span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

