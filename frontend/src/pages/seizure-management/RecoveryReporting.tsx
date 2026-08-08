import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { Download, Loader2, Search } from "lucide-react"
import { ModulePageLayout } from "@/components/dashboard/module-page-layout"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { ROUTES, getSeizureMgmtRecoveryMemoDetailPath } from "@/routes/config"
import { fetchRecoveryMemos, type RecoveryMemoRecord } from "@/lib/seizure-management-api"

export default function RecoveryReportingPage() {
  const [rows, setRows] = useState<RecoveryMemoRecord[]>([])
  const [search, setSearch] = useState("")
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    fetchRecoveryMemos()
      .then(setRows)
      .catch(() => setRows([]))
      .finally(() => setLoading(false))
  }, [])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return rows
    return rows.filter(
      (r) =>
        r.caseNo.toLowerCase().includes(q) ||
        r.category.toLowerCase().includes(q) ||
        r.approvalStatus.toLowerCase().includes(q)
    )
  }, [rows, search])

  const byCategory = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const r of rows) {
      counts[r.category] = (counts[r.category] ?? 0) + 1
    }
    return counts
  }, [rows])

  const exportCsv = () => {
    const header = ["Case No", "Category", "Date", "Officer", "Approval Status"]
    const lines = filtered.map((r) =>
      [r.caseNo, r.category, r.recoveryDate, r.recoveryOfficer, r.approvalStatus]
        .map((c) => `"${String(c).replace(/"/g, '""')}"`)
        .join(",")
    )
    const blob = new Blob([[header.join(","), ...lines].join("\n")], { type: "text/csv" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `recovery-report-${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <ModulePageLayout
      title="Recovery Reporting"
      description="Summary of recovery memos by category and approval status."
      breadcrumbs={[
        { label: "Seizure Management", href: ROUTES.SEIZURE_MANAGEMENT },
        { label: "Recovery Memo" },
        { label: "Reporting" },
      ]}
    >
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        {Object.entries(byCategory).map(([cat, count]) => (
          <Card key={cat} className="rounded-[10px]">
            <CardContent className="p-4">
              <p className="text-sm text-muted-foreground">{cat}</p>
              <p className="text-2xl font-bold">{count}</p>
            </CardContent>
          </Card>
        ))}
        {!loading && Object.keys(byCategory).length === 0 && (
          <Card className="rounded-[10px] sm:col-span-3">
            <CardContent className="p-4 text-sm text-muted-foreground">No recovery memos yet.</CardContent>
          </Card>
        )}
      </div>

      <Card className="rounded-[10px] border-gray-200">
        <CardContent className="p-6 space-y-4">
          <div className="flex flex-col sm:flex-row gap-3 sm:items-center sm:justify-between">
            <div className="relative flex-1 max-w-sm">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                className="pl-9"
                placeholder="Search..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <Button variant="outline" onClick={exportCsv} disabled={filtered.length === 0}>
              <Download className="h-4 w-4 mr-2" />
              Export CSV
            </Button>
          </div>

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Case No</TableHead>
                <TableHead>Category</TableHead>
                <TableHead>Date</TableHead>
                <TableHead>Officer</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Detail</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                    <Loader2 className="h-5 w-5 animate-spin inline mr-2" />
                    Loading...
                  </TableCell>
                </TableRow>
              ) : (
                filtered.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell className="font-medium">{row.caseNo}</TableCell>
                    <TableCell>{row.category}</TableCell>
                    <TableCell>{row.recoveryDate}</TableCell>
                    <TableCell>{row.recoveryOfficer}</TableCell>
                    <TableCell>
                      <Badge variant={row.approvalStatus === "Approved" ? "default" : "secondary"}>
                        {row.approvalStatus}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button variant="link" size="sm" asChild>
                        <Link to={getSeizureMgmtRecoveryMemoDetailPath(row.id)}>View</Link>
                      </Button>
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
