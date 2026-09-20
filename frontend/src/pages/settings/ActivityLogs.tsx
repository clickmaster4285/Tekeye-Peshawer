import { useEffect, useState } from "react"
import { useQuery, keepPreviousData } from "@tanstack/react-query"
import { FileText, Loader2, ChevronLeft, ChevronRight } from "lucide-react"
import { useNavigate } from "react-router-dom"
import { ModulePageLayout } from "@/components/dashboard/module-page-layout"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
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
import { fetchActivityLogs, type ActivityLogRecord } from "@/lib/logs-api"
import { getActivityLogDetailPath } from "@/routes/config"

const PAGE_SIZE_OPTIONS = [20, 50, 100] as const
const DEFAULT_PAGE_SIZE = 20

function formatTime(s: string | null | undefined) {
  if (!s) return "—"
  try {
    return new Date(s).toLocaleString(undefined, { dateStyle: "short", timeStyle: "medium" })
  } catch {
    return s
  }
}

function cell(value: string | null | undefined) {
  return value ?? "—"
}

export default function ActivityLogsPage() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState<number>(DEFAULT_PAGE_SIZE)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [filters, setFilters] = useState({
    username: "",
    ipAddress: "",
    country: "",
    city: "",
    device: "",
    os: "",
    browser: "",
    action: "",
    dateFrom: "",
    dateTo: "",
  })

  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handlePageSizeChange = (value: string) => {
    const next = Number(value) as (typeof PAGE_SIZE_OPTIONS)[number]
    setPageSize(next)
    setPage(1)
  }

  // Debounce text filters so each keystroke doesn't trigger a new request — the query
  // fires ~300ms after typing stops instead of on every character.
  const [debouncedFilters, setDebouncedFilters] = useState(filters)
  useEffect(() => {
    const id = window.setTimeout(() => setDebouncedFilters(filters), 300)
    return () => window.clearTimeout(id)
  }, [filters])

  useEffect(() => {
    setPage(1)
  }, [debouncedFilters])

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["activity-logs", page, pageSize, debouncedFilters],
    queryFn: () =>
      fetchActivityLogs({
        page,
        page_size: pageSize,
        username: debouncedFilters.username || undefined,
        ip_address: debouncedFilters.ipAddress || undefined,
        country: debouncedFilters.country || undefined,
        city: debouncedFilters.city || undefined,
        device: debouncedFilters.device || undefined,
        os: debouncedFilters.os || undefined,
        browser: debouncedFilters.browser || undefined,
        action: debouncedFilters.action || undefined,
        date_from: debouncedFilters.dateFrom || undefined,
        date_to: debouncedFilters.dateTo || undefined,
      }),
    // Keep showing the previous page's rows while the next page loads instead of a flash.
    placeholderData: keepPreviousData,
  })

  const pagedLogs = data?.results ?? []
  const count = data?.count ?? 0
  const hasNext = Boolean(data?.next)
  const hasPrev = Boolean(data?.previous)
  const from = count === 0 ? 0 : (page - 1) * pageSize + 1
  const to = Math.min(page * pageSize, count)

  const openLogDetail = (log: ActivityLogRecord) => {
    const sp = new URLSearchParams()
    if (log.username) sp.set("username", log.username)
    const qs = sp.toString()
    navigate(qs ? `${getActivityLogDetailPath(log.id)}?${qs}` : getActivityLogDetailPath(log.id))
  }

  return (
    <ModulePageLayout
      title="Logs"
      description="User activity logs — actions, IP, device, and time. Sorted by newest first."
      breadcrumbs={[{ label: "System configuration" }, { label: "Logs" }]}
    >
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-[#3b82f6]" />
            Activity logs
          </CardTitle>
          <CardDescription>
            All user activity recorded by the system. Requires authentication to view.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!isLoading && !isError && (
            <div className="mb-4 rounded-md border p-3">
              <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-5">
                <Input
                  placeholder="Filter user"
                  value={filters.username}
                  onChange={(e) => setFilters((prev) => ({ ...prev, username: e.target.value }))}
                />
                <Input
                  placeholder="Filter IP address"
                  value={filters.ipAddress}
                  onChange={(e) => setFilters((prev) => ({ ...prev, ipAddress: e.target.value }))}
                />
                <Input
                  placeholder="Filter country"
                  value={filters.country}
                  onChange={(e) => setFilters((prev) => ({ ...prev, country: e.target.value }))}
                />
                <Input
                  placeholder="Filter city"
                  value={filters.city}
                  onChange={(e) => setFilters((prev) => ({ ...prev, city: e.target.value }))}
                />
                <Input
                  placeholder="Filter device"
                  value={filters.device}
                  onChange={(e) => setFilters((prev) => ({ ...prev, device: e.target.value }))}
                />
                <Input
                  placeholder="Filter OS"
                  value={filters.os}
                  onChange={(e) => setFilters((prev) => ({ ...prev, os: e.target.value }))}
                />
                <Input
                  placeholder="Filter browser"
                  value={filters.browser}
                  onChange={(e) => setFilters((prev) => ({ ...prev, browser: e.target.value }))}
                />
                <Input
                  placeholder="Filter action"
                  value={filters.action}
                  onChange={(e) => setFilters((prev) => ({ ...prev, action: e.target.value }))}
                />
                <Input
                  type="date"
                  value={filters.dateFrom}
                  onChange={(e) => setFilters((prev) => ({ ...prev, dateFrom: e.target.value }))}
                />
                <Input
                  type="date"
                  value={filters.dateTo}
                  onChange={(e) => setFilters((prev) => ({ ...prev, dateTo: e.target.value }))}
                />
              </div>
              <div className="mt-3 flex justify-end">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    setFilters({
                      username: "",
                      ipAddress: "",
                      country: "",
                      city: "",
                      device: "",
                      os: "",
                      browser: "",
                      action: "",
                      dateFrom: "",
                      dateTo: "",
                    })
                  }
                >
                  Clear filters
                </Button>
              </div>
            </div>
          )}
          {isLoading && (
            <div className="flex justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-[#3b82f6]" />
            </div>
          )}
          {isError && (
            <div className="rounded-lg border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
              {error instanceof Error ? error.message : "Failed to load logs"}
            </div>
          )}
          {!isLoading && !isError && (
            <>
              <div className="rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-[50px]">
                        <span className="sr-only">Select</span>
                      </TableHead>
                      <TableHead className="uppercase text-xs font-semibold">User</TableHead>
                      <TableHead className="uppercase text-xs font-semibold">IP Address</TableHead>
                      <TableHead className="uppercase text-xs font-semibold">Country</TableHead>
                      <TableHead className="uppercase text-xs font-semibold">City</TableHead>
                      <TableHead className="uppercase text-xs font-semibold">Device</TableHead>
                      <TableHead className="uppercase text-xs font-semibold">OS</TableHead>
                      <TableHead className="uppercase text-xs font-semibold">Browser</TableHead>
                      <TableHead className="uppercase text-xs font-semibold">Action</TableHead>
                      <TableHead className="uppercase text-xs font-semibold w-[160px]">Time</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {pagedLogs.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={10} className="text-center text-muted-foreground py-8">
                          No logs match the selected filters.
                        </TableCell>
                      </TableRow>
                    ) : (
                      (pagedLogs as ActivityLogRecord[]).map((log) => (
                        <TableRow
                          key={log.id}
                          className="cursor-pointer"
                          onClick={() => openLogDetail(log)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault()
                              openLogDetail(log)
                            }
                          }}
                          tabIndex={0}
                          role="button"
                          aria-label={`Open details for log ${log.id}`}
                        >
                          <TableCell className="w-[50px]">
                            <Checkbox
                              checked={selectedIds.has(log.id)}
                              onCheckedChange={() => toggleSelect(log.id)}
                              onClick={(e) => e.stopPropagation()}
                              aria-label={`Select log ${log.id}`}
                            />
                          </TableCell>
                          <TableCell>{cell(log.username)}</TableCell>
                          <TableCell className="text-muted-foreground">{cell(log.ip_address)}</TableCell>
                          <TableCell className="text-muted-foreground">{cell(log.country)}</TableCell>
                          <TableCell className="text-muted-foreground">{cell(log.city)}</TableCell>
                          <TableCell className="text-muted-foreground">{cell(log.device)}</TableCell>
                          <TableCell className="text-muted-foreground">{cell(log.os)}</TableCell>
                          <TableCell className="text-muted-foreground">{cell(log.browser)}</TableCell>
                          <TableCell className="font-mono text-xs max-w-[220px] truncate" title={log.action}>
                            {cell(log.action)}
                          </TableCell>
                          <TableCell className="whitespace-nowrap text-muted-foreground">
                            {formatTime(log.time)}
                          </TableCell>
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>
              </div>
              {count > 0 && (
                <div className="flex flex-wrap items-center justify-between gap-4 mt-4">
                  <div className="flex items-center gap-4">
                    <p className="text-sm text-muted-foreground">
                      Showing {from}–{to} of {count}
                    </p>
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-muted-foreground whitespace-nowrap">Rows per page</span>
                      <Select
                        value={String(pageSize)}
                        onValueChange={handlePageSizeChange}
                      >
                        <SelectTrigger className="w-[72px]" size="sm">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {PAGE_SIZE_OPTIONS.map((size) => (
                            <SelectItem key={size} value={String(size)}>
                              {size}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                      disabled={!hasPrev}
                    >
                      <ChevronLeft className="h-4 w-4" />
                      Previous
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setPage((p) => p + 1)}
                      disabled={!hasNext}
                    >
                      Next
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </ModulePageLayout>
  )
}
