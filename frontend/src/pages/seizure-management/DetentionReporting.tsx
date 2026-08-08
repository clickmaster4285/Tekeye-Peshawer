import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { AlertTriangle, Download, Search } from "lucide-react"
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
import { ROUTES, getDetentionMemoDetailPath } from "@/routes/config"
import { fetchDetentionMemos, type DetentionMemoApiRecord } from "@/lib/detention-memo-api"
import {
  DETENTION_WINDOW_DAYS,
  daysSinceDetention,
  fetchAssessments,
  type DetentionAssessmentRecord,
} from "@/lib/seizure-management-api"

export default function DetentionReportingPage() {
  const [rows, setRows] = useState<DetentionMemoApiRecord[]>([])
  const [assessments, setAssessments] = useState<DetentionAssessmentRecord[]>([])
  const [search, setSearch] = useState("")
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    Promise.all([
      fetchDetentionMemos().catch(() => [] as DetentionMemoApiRecord[]),
      fetchAssessments().catch(() => [] as DetentionAssessmentRecord[]),
    ])
      .then(([memos, assess]) => {
        setRows(memos)
        setAssessments(assess)
      })
      .finally(() => setLoading(false))
  }, [])

  const assessedMemoIds = useMemo(() => {
    const set = new Set<string>()
    for (const a of assessments) set.add(a.detentionMemoId)
    return set
  }, [assessments])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return rows
    return rows.filter(
      (r) =>
        r.caseNo.toLowerCase().includes(q) ||
        r.placeOfDetention.toLowerCase().includes(q) ||
        (r.verificationStatus ?? "").toLowerCase().includes(q)
    )
  }, [rows, search])

  const stats = useMemo(() => {
    const overdue = rows.filter((r) => {
      const days = daysSinceDetention(r.dateTimeDetention)
      return days !== null && days > DETENTION_WINDOW_DAYS
    }).length
    const withAssessment = rows.filter((r) => assessedMemoIds.has(r.id)).length
    return { total: rows.length, overdue, withAssessment }
  }, [rows, assessedMemoIds])

  const exportCsv = () => {
    const header = ["Case No", "Detention Date", "Place", "Verification", "Days", "Assessment", "60-Day Status"]
    const lines = filtered.map((r) => {
      const days = daysSinceDetention(r.dateTimeDetention)
      const hasAssessment = assessedMemoIds.has(r.id)
      const windowStatus =
        days === null ? "" : days > DETENTION_WINDOW_DAYS ? "Overdue" : "Within window"
      return [
        r.caseNo,
        r.dateTimeDetention,
        r.placeOfDetention,
        r.verificationStatus ?? "",
        days ?? "",
        hasAssessment ? "Yes" : "No",
        windowStatus,
      ]
        .map((c) => `"${String(c).replace(/"/g, '""')}"`)
        .join(",")
    })
    const blob = new Blob([[header.join(","), ...lines].join("\n")], { type: "text/csv" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `detention-report-${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <ModulePageLayout
      title="Detention Reporting"
      description="Summary of detention memos, assessment coverage, and 60-day recovery window compliance."
      breadcrumbs={[
        { label: "Seizure Management", href: ROUTES.SEIZURE_MANAGEMENT },
        { label: "Detention" },
        { label: "Reporting" },
      ]}
    >
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <Card className="rounded-[10px]">
          <CardContent className="p-4">
            <p className="text-sm text-muted-foreground">Total Memos</p>
            <p className="text-2xl font-bold">{stats.total}</p>
          </CardContent>
        </Card>
        <Card className="rounded-[10px]">
          <CardContent className="p-4">
            <p className="text-sm text-muted-foreground">With Assessment</p>
            <p className="text-2xl font-bold">{stats.withAssessment}</p>
          </CardContent>
        </Card>
        <Card className="rounded-[10px] border-amber-200">
          <CardContent className="p-4">
            <p className="text-sm text-muted-foreground">Over {DETENTION_WINDOW_DAYS} Days</p>
            <p className="text-2xl font-bold text-amber-700">{stats.overdue}</p>
          </CardContent>
        </Card>
      </div>

      <Card className="rounded-[10px] border-gray-200">
        <CardContent className="p-6 space-y-4">
          <div className="flex flex-col sm:flex-row gap-3 sm:items-center sm:justify-between">
            <div className="relative flex-1 max-w-sm">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                className="pl-9"
                placeholder="Search case no, place..."
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
                <TableHead>Detention Date</TableHead>
                <TableHead>Place</TableHead>
                <TableHead>Days</TableHead>
                <TableHead>Assessment</TableHead>
                <TableHead>Window</TableHead>
                <TableHead className="text-right">Memo</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-8 text-muted-foreground">
                    Loading...
                  </TableCell>
                </TableRow>
              ) : filtered.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-8 text-muted-foreground">
                    No detention memos found.
                  </TableCell>
                </TableRow>
              ) : (
                filtered.map((row) => {
                  const days = daysSinceDetention(row.dateTimeDetention)
                  const overdue = days !== null && days > DETENTION_WINDOW_DAYS
                  const hasAssessment = assessedMemoIds.has(row.id)
                  return (
                    <TableRow key={row.id}>
                      <TableCell className="font-medium">{row.caseNo}</TableCell>
                      <TableCell>{row.dateTimeDetention?.slice(0, 10) ?? "—"}</TableCell>
                      <TableCell>{row.placeOfDetention}</TableCell>
                      <TableCell>{days ?? "—"}</TableCell>
                      <TableCell>
                        <Badge variant={hasAssessment ? "default" : "outline"}>
                          {hasAssessment ? "Done" : "Pending"}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        {overdue ? (
                          <Badge variant="destructive" className="gap-1">
                            <AlertTriangle className="h-3 w-3" />
                            Overdue
                          </Badge>
                        ) : (
                          <Badge variant="secondary">OK</Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button variant="link" size="sm" asChild>
                          <Link to={getDetentionMemoDetailPath(row.id)}>View</Link>
                        </Button>
                      </TableCell>
                    </TableRow>
                  )
                })
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </ModulePageLayout>
  )
}
