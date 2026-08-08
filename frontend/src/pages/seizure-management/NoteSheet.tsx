import { useEffect, useMemo, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { Plus, Search } from "lucide-react"
import { ModulePageLayout } from "@/components/dashboard/module-page-layout"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  ROUTES,
  getSeizureMgmtNoteSheetDetailPath,
  getSeizureMgmtNoteSheetEditPath,
} from "@/routes/config"
import { fetchNoteSheets, type NoteSheetRecord, type NoteSheetStatus } from "@/lib/seizure-management-api"

function statusBadge(status: NoteSheetStatus) {
  if (status === "Approved") return <Badge>Approved</Badge>
  if (status === "Submitted") return <Badge variant="secondary">Submitted</Badge>
  if (status === "Rejected") return <Badge variant="destructive">Rejected</Badge>
  return <Badge variant="outline">Draft</Badge>
}

export default function NoteSheetPage() {
  const navigate = useNavigate()
  const [rows, setRows] = useState<NoteSheetRecord[]>([])
  const [search, setSearch] = useState("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    fetchNoteSheets()
      .then(setRows)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
  }, [])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return rows
    return rows.filter(
      (r) =>
        (r.noteSheetNo || "").toLowerCase().includes(q) ||
        r.referenceNumber.toLowerCase().includes(q) ||
        r.subject.toLowerCase().includes(q) ||
        r.caseNo.toLowerCase().includes(q) ||
        (r.office || "").toLowerCase().includes(q) ||
        r.preparedBy.toLowerCase().includes(q) ||
        r.status.toLowerCase().includes(q) ||
        (r.priority || "").toLowerCase().includes(q)
    )
  }, [rows, search])

  return (
    <ModulePageLayout
      title="Note Sheet"
      description="Create and get officer approval on a note sheet before creating a detention memo."
      breadcrumbs={[
        { label: "Seizure Management", href: ROUTES.SEIZURE_MANAGEMENT },
        { label: "Note Sheet" },
      ]}
    >
      <Card className="rounded-[10px] border-gray-200">
        <CardContent className="p-6 space-y-4">
          <div className="flex flex-col sm:flex-row gap-3 sm:items-center sm:justify-between">
            <div className="relative flex-1 max-w-sm">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                className="pl-9"
                placeholder="Search note sheet no, subject, case..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <Button asChild>
              <Link to={ROUTES.SEIZURE_MGMT_NOTE_SHEET_CREATE}>
                <Plus className="h-4 w-4 mr-2" />
                New Note Sheet
              </Link>
            </Button>
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Note Sheet No.</TableHead>
                <TableHead>Subject</TableHead>
                <TableHead>Case No</TableHead>
                <TableHead>Office</TableHead>
                <TableHead>Priority</TableHead>
                <TableHead>Prepared By</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Detention Memo</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={9} className="text-center py-8 text-muted-foreground">
                    Loading...
                  </TableCell>
                </TableRow>
              ) : filtered.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={9} className="text-center py-8 text-muted-foreground">
                    No note sheets yet.
                  </TableCell>
                </TableRow>
              ) : (
                filtered.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell className="font-medium font-mono text-sm">
                      {row.noteSheetNo || row.referenceNumber || "—"}
                    </TableCell>
                    <TableCell className="max-w-[200px] truncate">{row.subject || "—"}</TableCell>
                    <TableCell>{row.caseNo || "—"}</TableCell>
                    <TableCell>{row.office || "—"}</TableCell>
                    <TableCell>{row.priority || "—"}</TableCell>
                    <TableCell>{row.preparedBy || "—"}</TableCell>
                    <TableCell>{statusBadge(row.status)}</TableCell>
                    <TableCell>
                      {row.detentionMemoId ? (
                        <Badge variant="outline">Linked</Badge>
                      ) : row.status === "Approved" ? (
                        <Badge className="bg-green-100 text-green-800 hover:bg-green-100">Ready</Badge>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell className="text-right space-x-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => navigate(getSeizureMgmtNoteSheetDetailPath(row.id))}
                      >
                        View
                      </Button>
                      {(row.status === "Draft" || row.status === "Rejected") && (
                        <Button variant="outline" size="sm" asChild>
                          <Link to={getSeizureMgmtNoteSheetEditPath(row.id)}>Edit</Link>
                        </Button>
                      )}
                      {row.status === "Approved" && !row.detentionMemoId && (
                        <Button size="sm" asChild>
                          <Link to={`${ROUTES.DETENTION_MEMO_CREATE}?noteSheetId=${encodeURIComponent(row.id)}`}>
                            Create Detention Memo
                          </Link>
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </ModulePageLayout>
  )
}
