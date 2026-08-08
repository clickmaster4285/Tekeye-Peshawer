import { useEffect, useMemo, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { AlertTriangle, BookOpen, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, Eye, Package, Plus, Printer, Search, CheckCircle, Clock, Edit2, Trash2 } from "lucide-react"
import { ModulePageLayout } from "@/components/dashboard/module-page-layout"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
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
import { Badge } from "@/components/ui/badge"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { ROUTES, getDetentionMemoDetailPath } from "@/routes/config"
import { fetchDetentionMemos, deleteDetentionMemo, type DetentionMemoApiRecord } from "@/lib/detention-memo-api"
import { createDepositAccountEntry, fetchDepositAccounts } from "@/lib/deposit-account-api"
import { promoteDetentionToSeizedAndInventory } from "@/lib/wms-stock-storage"
import { toast } from "@/components/ui/use-toast"
const PAGE_SIZE_OPTIONS = [10, 25, 50, 100]
const DEFAULT_PAGE_SIZE = 10
const DETENTION_ALERT_DAYS = 60

type DetentionMemoRow = DetentionMemoApiRecord & {
  serialNo?: number
  year?: number
}

function extractSerialInfo(caseNo: string): { serialNo: number; year: number } | null {
  const match = caseNo.match(/(\d+)\/(\d{4})/)
  if (match) {
    return { serialNo: parseInt(match[1], 10), year: parseInt(match[2], 10) }
  }
  return null
}

function isDetentionOverTwoMonths(dateTimeDetention: string): boolean {
  if (!dateTimeDetention?.trim()) return false
  try {
    const det = new Date(dateTimeDetention.replace(" ", "T"))
    const days = (new Date().getTime() - det.getTime()) / (1000 * 60 * 60 * 24)
    return days > DETENTION_ALERT_DAYS
  } catch {
    return false
  }
}

function printMemo(id: string) {
  const reportUrl = `${getDetentionMemoDetailPath(id)}?print=full&autoprint=1`
  window.location.assign(reportUrl)
}

function printQr(id: string) {
  const reportUrl = `${getDetentionMemoDetailPath(id)}?print=qr&autoprint=1`
  window.location.assign(reportUrl)
}

export default function DetentionMemoPage() {
  const navigate = useNavigate()
  const [rows, setRows] = useState<DetentionMemoRow[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [caseNumberSearch, setCaseNumberSearch] = useState("")
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
  const [page, setPage] = useState(1)
  const [memoIdsWithDeposit, setMemoIdsWithDeposit] = useState<Set<string>>(() => new Set())
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<DetentionMemoRow | null>(null)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLoadError(null)
    Promise.all([fetchDetentionMemos(), fetchDepositAccounts().catch(() => [])])
      .then(([list, deposits]) => {
        if (cancelled) return
        const ids = new Set<string>()
        for (const d of deposits) {
          const mid = d.detentionMemoId?.trim()
          if (mid) ids.add(mid)
        }
        setMemoIdsWithDeposit(ids)
        const mapped = list.map((r) => {
          const serialInfo = extractSerialInfo(r.caseNo)
          return {
            ...r,
            updatedAt: r.updatedAt ?? r.createdAt,
            createdBy: r.createdBy ?? "ASO Portal",
            serialNo: serialInfo?.serialNo,
            year: serialInfo?.year,
          }
        })
        setRows(mapped)
      })
      .catch((e) => {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : "Failed to load detention memos.")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const filteredRows = useMemo(() => {
    if (!caseNumberSearch.trim()) return rows
    const q = caseNumberSearch.trim().toLowerCase()
    return rows.filter(
      (r) =>
        r.caseNo.toLowerCase().includes(q) ||
        (r.referenceNumber ?? "").toLowerCase().includes(q)
    )
  }, [rows, caseNumberSearch])

  const totalPages = Math.max(1, Math.ceil(filteredRows.length / pageSize))
  const pageRows = useMemo(() => filteredRows.slice((page - 1) * pageSize, page * pageSize), [filteredRows, page, pageSize])

  const handleSearch = () => setPage(1)
  const handleClear = () => { setCaseNumberSearch(""); setPage(1) }
  
  const handleSeize = async (row: DetentionMemoRow) => {
    const ok = await promoteDetentionToSeizedAndInventory(row)
    if (ok) {
      alert(
        `✓ Case ${row.caseNo || row.id} added to Seizure Register and Stock Management.\n` +
          "All goods lines are in stock with the detention case number linked."
      )
    } else {
      alert("✗ Could not add to Seizure Register.")
    }
  }

  const handleDeposit = async (row: DetentionMemoRow) => {
    if (memoIdsWithDeposit.has(row.id)) return
    try {
      await createDepositAccountEntry({
        detentionMemoId: row.id,
        treasuryChallanNo: "",
        depositType: "Detention",
        caseSeizureRef: row.caseNo,
        firNo: "",
        customsStation: row.placeOfDetention,
        amount: "",
        depositDate: new Date().toISOString().slice(0, 10),
        bankTreasuryName: "",
        status: "Pending",
        remarks:
          `Detention deposit linked to memo ${row.caseNo}` +
          (row.referenceNumber ? ` (ref ${row.referenceNumber})` : ""),
      })
      setMemoIdsWithDeposit((prev) => new Set(prev).add(row.id))
      alert(
        "Deposit entry saved on the server.\n\nGo to Detentions → Deposit Account Register to add treasury challan, amount, or bank details when issued."
      )
    } catch (e) {
      alert(
        `Could not save deposit: ${e instanceof Error ? e.message : "unknown error"}\n\nCheck that the API is running (VITE_API_BASE_URL).`
      )
    }
  }

  const handleDeleteClick = (row: DetentionMemoRow) => {
    setDeleteTarget(row)
    setDeleteConfirmOpen(true)
  }

  const confirmDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await deleteDetentionMemo(deleteTarget.id)
      toast({
        title: "Deleted",
        description: `Detention memo ${deleteTarget.caseNo} has been removed.`,
      })
      setDeleteConfirmOpen(false)
      setDeleteTarget(null)
      setRows((prev) => prev.filter((r) => r.id !== deleteTarget.id))
    } catch (e) {
      toast({
        title: "Delete failed",
        description: e instanceof Error ? e.message : "Could not delete memo.",
        variant: "destructive",
      })
    } finally {
      setDeleting(false)
    }
  }

  const handleEdit = (row: DetentionMemoRow) => {
    navigate(getDetentionMemoDetailPath(row.id))
  }

  return (
    <ModulePageLayout
      title="Detention Memo"
      description="Create, view, and print detention memo records with QR-enabled report access. Deposit is available once per memo (disabled after a linked Deposit Account Register entry exists)."
      breadcrumbs={[
        { label: "Seizure Management", href: ROUTES.SEIZURE_MANAGEMENT },
        { label: "Detention Memo" },
      ]}
    >
      <div className="grid gap-6">
        <Card className="w-full min-w-0 border-0 shadow-sm">
          <CardContent className="w-full min-w-0 pt-6">
            {loadError && (
              <div className="mb-4 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {loadError}
              </div>
            )}
            {loading && (
              <p className="mb-4 text-sm text-muted-foreground">Loading detention memos…</p>
            )}
            {/* Header with Add Button */}
            <div className="mb-6 flex flex-wrap items-start justify-between gap-3 sm:items-center sm:gap-4">
              <div className="flex flex-wrap gap-2">
                <Button className="bg-primary text-primary-foreground hover:bg-primary/90 shadow-sm" asChild>
                  <Link to={ROUTES.SEIZURE_MGMT_NOTE_SHEET}>
                    <Plus className="h-4 w-4 mr-2" />
                    Note Sheet / New Detention
                  </Link>
                </Button>
                <Button variant="outline" asChild>
                  <Link to={ROUTES.DETENTION_MEMO_CREATE}>
                    Create Detention Memo
                  </Link>
                </Button>
              </div>
              <div className="flex w-full flex-col gap-1 text-sm text-muted-foreground sm:w-auto sm:items-end">
                <span>
                  Total Records: <span className="font-semibold text-foreground">{filteredRows.length}</span>
                </span>
                <p className="text-xs">Detention memo requires an approved note sheet.</p>
                <Link className="text-primary hover:underline" to={ROUTES.DEPOSIT_ACCOUNT_REGISTER}>
                  Open Deposit Account Register
                </Link>
              </div>
            </div>

            {/* Search Bar */}
            <div className="mb-6 flex flex-wrap items-end gap-3">
              <div className="min-w-0 flex-1 sm:min-w-[240px]">
                <Label className="text-sm font-medium mb-2 block">Case Number</Label>
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    value={caseNumberSearch}
                    onChange={(e) => setCaseNumberSearch(e.target.value)}
                    placeholder="Search by case number..."
                    className="pl-9"
                    onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                  />
                </div>
              </div>
              <Button onClick={handleSearch} className="w-full gap-2 sm:w-auto">
                <Search className="h-4 w-4" />
                Search
              </Button>
              <Button variant="outline" onClick={handleClear} className="w-full gap-2 sm:w-auto">
                Clear
              </Button>
            </div>

            {/* Mobile list */}
            <div className="space-y-3 md:hidden">
              {pageRows.length === 0 ? (
                <div className="rounded-lg border bg-background px-4 py-10 text-center text-muted-foreground">
                  <Package className="mx-auto mb-3 h-10 w-10 opacity-30" />
                  No detention memos found
                </div>
              ) : (
                pageRows.map((row, index) => {
                  const serialInfo = extractSerialInfo(row.caseNo)
                  const isAlert = isDetentionOverTwoMonths(row.dateTimeDetention)
                  return (
                    <div key={row.id} className="rounded-lg border bg-background p-3 shadow-sm">
                      <div className="mb-2 flex items-start justify-between gap-3">
                        <div>
                          <p className="text-xs text-muted-foreground">Sr.No</p>
                          <p className="font-mono text-xs font-medium">
                            {serialInfo ? `${serialInfo.serialNo}/${serialInfo.year}` : row.serialNo ?? index + 1}
                          </p>
                        </div>
                        {row.verificationStatus === "Verified" ? (
                          <Badge className="gap-1 bg-green-100 text-green-800 hover:bg-green-100">
                            <CheckCircle className="h-3 w-3" /> Verified
                          </Badge>
                        ) : (
                          <Badge variant="secondary" className="gap-1">
                            <Clock className="h-3 w-3" /> {row.verificationStatus}
                          </Badge>
                        )}
                      </div>

                      <div className="grid grid-cols-1 gap-2 text-sm">
                        <div>
                          <p className="text-xs text-muted-foreground">Case Number</p>
                          <p className="font-medium">{row.caseNo}</p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">Detention Memo No</p>
                          <p className="font-mono text-xs">{row.referenceNumber || "—"}</p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">Detention Date/Time</p>
                          <p>{row.dateTimeDetention || "—"}</p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">Posting / Updation</p>
                          <p>{row.createdAt || "—"} / {row.updatedAt ?? row.createdAt ?? "—"}</p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">Created By</p>
                          <p>{row.createdBy || "ASO Portal"}</p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">Alert</p>
                          {isAlert ? (
                            <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-700">
                              <AlertTriangle className="h-3.5 w-3.5" />
                              Over 60 days
                            </span>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </div>
                      </div>

                      <div className="mt-3 grid grid-cols-2 gap-2">
                        <Button variant="ghost" size="sm" asChild className="h-8 px-2">
                          <Link to={getDetentionMemoDetailPath(row.id)}>
                            <Eye className="mr-1 h-3.5 w-3.5" /> View
                          </Link>
                        </Button>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="outline" size="sm" className="h-8 px-2">
                              <Printer className="mr-1 h-3.5 w-3.5" /> Print
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem onClick={() => printQr(row.id)}>Print QR Code</DropdownMenuItem>
                            <DropdownMenuItem onClick={() => printMemo(row.id)}>Print Full Report</DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={memoIdsWithDeposit.has(row.id)}
                          title={memoIdsWithDeposit.has(row.id) ? "Already deposited — open Deposit Account Register for this memo" : "Add to Deposit Account Register"}
                          onClick={() => void handleDeposit(row)}
                          className="h-8 px-2"
                        >
                          <BookOpen className="mr-1 h-3.5 w-3.5" /> Deposit
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => void handleSeize(row)} className="h-8 px-2">
                          <Package className="mr-1 h-3.5 w-3.5" /> Seize
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => handleEdit(row)} className="h-8 px-2">
                          <Edit2 className="mr-1 h-3.5 w-3.5" /> Edit
                        </Button>
                        <Button variant="destructive" size="sm" onClick={() => handleDeleteClick(row)} className="h-8 px-2">
                          <Trash2 className="mr-1 h-3.5 w-3.5" /> Delete
                        </Button>
                      </div>
                    </div>
                  )
                })
              )}
            </div>

            {/* Desktop table */}
            <div className="hidden w-full min-w-0 overflow-hidden rounded-lg border bg-background md:block">
              <div className="max-h-[65vh] w-full max-w-full overflow-x-auto overflow-y-auto pb-2">
                <Table className="min-w-[1400px]">
                  <TableHeader className="sticky top-0 bg-muted/50 backdrop-blur-sm">
                    <TableRow className="hover:bg-transparent">
                      <TableHead className="w-[80px] font-semibold">Sr.No</TableHead>
                      <TableHead className="font-semibold">Case Number</TableHead>
                      <TableHead className="font-semibold">Detention Memo No</TableHead>
                      <TableHead className="font-semibold">Detention Date/Time</TableHead>
                      <TableHead className="font-semibold">Status</TableHead>
                      <TableHead className="font-semibold">Posting Date</TableHead>
                      <TableHead className="font-semibold">Updation Date</TableHead>
                      <TableHead className="font-semibold">Alert</TableHead>
                      <TableHead className="font-semibold">created by </TableHead>
                      <TableHead className="text-right font-semibold">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {pageRows.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={10} className="text-center py-12 text-muted-foreground">
                          <Package className="h-12 w-12 mx-auto mb-3 opacity-30" />
                          No detention memos found
                        </TableCell>
                      </TableRow>
                    ) : (
                      pageRows.map((row, index) => {
                        const serialInfo = extractSerialInfo(row.caseNo)
                        const isAlert = isDetentionOverTwoMonths(row.dateTimeDetention)
                        return (
                          <TableRow key={row.id} className="hover:bg-muted/40 transition-colors">
                            <TableCell className="font-mono text-xs">
                              {serialInfo ? `${serialInfo.serialNo}/${serialInfo.year}` : row.serialNo ?? index + 1}
                            </TableCell>
                            <TableCell className="font-medium">{row.caseNo}</TableCell>
                            <TableCell className="font-mono text-xs">{row.referenceNumber || "—"}</TableCell>
                            <TableCell className="whitespace-nowrap text-sm">{row.dateTimeDetention || "—"}</TableCell>
                            <TableCell>
                              {row.verificationStatus === "Verified" ? (
                                <Badge className="bg-green-100 text-green-800 hover:bg-green-100 gap-1">
                                  <CheckCircle className="h-3 w-3" /> Verified
                                </Badge>
                              ) : (
                                <Badge variant="secondary" className="gap-1">
                                  <Clock className="h-3 w-3" /> {row.verificationStatus}
                                </Badge>
                              )}
                            </TableCell>
                            <TableCell className="text-sm">{row.createdAt || "—"}</TableCell>
                            <TableCell className="text-sm">{row.updatedAt ?? row.createdAt ?? "—"}</TableCell>
                            <TableCell>
                              {isAlert ? (
                                <div className="group relative inline-block">
                                  <span className="inline-flex items-center gap-1.5 bg-amber-50 text-amber-700 text-xs font-medium px-2.5 py-1 rounded-full border border-amber-200">
                                    <AlertTriangle className="h-3.5 w-3.5" />
                                    <span>Over 60 days</span>
                                  </span>
                                  <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-2 py-1 bg-gray-900 text-white text-xs rounded opacity-0 group-hover:opacity-100 transition pointer-events-none whitespace-nowrap z-10">
                                    Transfer to Seizure Register if applicable
                                  </div>
                                </div>
                              ) : (
                                <span className="text-muted-foreground text-sm">—</span>
                              )}
                            </TableCell>
                            <TableCell className="text-sm">{row.createdBy || "ASO Portal"}</TableCell>
                            <TableCell className="text-right">
                              <div className="flex flex-wrap justify-end gap-1">
                                <Button variant="ghost" size="sm" asChild className="h-8 px-2">
                                  <Link to={getDetentionMemoDetailPath(row.id)}>
                                    <Eye className="h-3.5 w-3.5 mr-1" /> View
                                  </Link>
                                </Button>
                                <DropdownMenu>
                                  <DropdownMenuTrigger asChild>
                                    <Button variant="outline" size="sm" className="h-8 px-2">
                                      <Printer className="h-3.5 w-3.5 mr-1" /> Print
                                    </Button>
                                  </DropdownMenuTrigger>
                                  <DropdownMenuContent align="end">
                                    <DropdownMenuItem onClick={() => printQr(row.id)}>Print QR Code</DropdownMenuItem>
                                    <DropdownMenuItem onClick={() => printMemo(row.id)}>Print Full Report</DropdownMenuItem>
                                  </DropdownMenuContent>
                                </DropdownMenu>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  disabled={memoIdsWithDeposit.has(row.id)}
                                  title={memoIdsWithDeposit.has(row.id) ? "Already deposited — open Deposit Account Register for this memo" : "Add to Deposit Account Register"}
                                  onClick={() => void handleDeposit(row)}
                                  className="h-8 px-2"
                                >
                                  <BookOpen className="h-3.5 w-3.5 mr-1" /> Deposit
                                </Button>
                                <Button variant="outline" size="sm" onClick={() => void handleSeize(row)} className="h-8 px-2">
                                  <Package className="h-3.5 w-3.5 mr-1" /> Seize
                                </Button>
                                <Button variant="outline" size="sm" onClick={() => handleEdit(row)} className="h-8 px-2">
                                  <Edit2 className="h-3.5 w-3.5 mr-1" /> Edit
                                </Button>
                                <Button variant="destructive" size="sm" onClick={() => handleDeleteClick(row)} className="h-8 px-2">
                                  <Trash2 className="h-3.5 w-3.5 mr-1" /> Delete
                                </Button>
                              </div>
                            </TableCell>
                          </TableRow>
                        )
                      })
                    )}
                  </TableBody>
                </Table>
              </div>
            </div>

            {/* Pagination */}
            {filteredRows.length > 0 && (
              <div className="mt-6 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-sm text-muted-foreground">Rows per page:</span>
                  <Select
                    value={pageSize.toString()}
                    onValueChange={(value) => {
                      setPageSize(Number(value))
                      setPage(1)
                    }}
                  >
                    <SelectTrigger className="w-[80px] h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PAGE_SIZE_OPTIONS.map(size => (
                        <SelectItem key={size} value={size.toString()}>{size}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                
                <div className="text-center text-sm text-muted-foreground lg:text-left">
                  Showing {((page - 1) * pageSize) + 1} to {Math.min(page * pageSize, filteredRows.length)} of {filteredRows.length} entries
                </div>
                
                <div className="flex flex-wrap items-center justify-center gap-1 lg:justify-end">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage(1)}
                    disabled={page === 1}
                    className="h-8 w-8 p-0"
                  >
                    <ChevronsLeft className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage(prev => Math.max(1, prev - 1))}
                    disabled={page === 1}
                    className="h-8 w-8 p-0"
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </Button>
                  <span className="px-3 text-sm">
                    Page {page} of {totalPages}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage(prev => Math.min(totalPages, prev + 1))}
                    disabled={page === totalPages}
                    className="h-8 w-8 p-0"
                  >
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage(totalPages)}
                    disabled={page === totalPages}
                    className="h-8 w-8 p-0"
                  >
                    <ChevronsRight className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <AlertDialog open={deleteConfirmOpen} onOpenChange={setDeleteConfirmOpen}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Delete Detention Memo?</AlertDialogTitle>
              <AlertDialogDescription>
                This will permanently delete the detention memo for case {deleteTarget?.caseNo}. This action cannot be undone.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <div className="flex gap-4 justify-end">
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction
                onClick={() => void confirmDelete()}
                disabled={deleting}
                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              >
                {deleting ? "Deleting..." : "Delete"}
              </AlertDialogAction>
            </div>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </ModulePageLayout>
  )
}