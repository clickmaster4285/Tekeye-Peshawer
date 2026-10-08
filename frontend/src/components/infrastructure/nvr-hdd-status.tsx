import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { NvrHddDisk } from "@/lib/infrastructure-api"
import { cn } from "@/lib/utils"

/** Exact NVR Storage UI statuses: Normal | Sleep | Error | Abnormal | Offline | Unformatted | Full | Unknown */
function hddStatusTone(status: string) {
  const s = (status || "").trim().toLowerCase()
  if (s === "normal") return "bg-emerald-100 text-emerald-800 border-emerald-200"
  if (s === "sleep" || s === "idle") return "bg-slate-100 text-slate-800 border-slate-300"
  if (s === "full") return "bg-amber-100 text-amber-900 border-amber-200"
  if (s === "error" || s === "abnormal" || s === "offline" || s === "unformatted") {
    return "bg-red-100 text-red-800 border-red-200"
  }
  return "bg-slate-100 text-slate-700 border-slate-200"
}

function hddStatusDot(status: string) {
  const s = (status || "").trim().toLowerCase()
  if (s === "normal") return "bg-emerald-500"
  if (s === "sleep" || s === "idle") return "bg-slate-400"
  if (s === "full") return "bg-amber-500"
  if (s === "error" || s === "abnormal" || s === "offline" || s === "unformatted") {
    return "bg-red-500"
  }
  return "bg-slate-400"
}

/** Same columns as NVR Detail → Storage: Disk No. / Remaining / Capacity / Status / Attribute / Type */
export function NvrHddStatusList({
  disks,
  className,
}: {
  disks: NvrHddDisk[]
  className?: string
}) {
  if (!disks.length) {
    return (
      <p className="text-xs text-muted-foreground whitespace-nowrap">No drive data — Poll NVR</p>
    )
  }

  return (
    <div className={cn("overflow-x-auto rounded-md border border-border/80 bg-background", className)}>
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            {[
              "Disk No.",
              "Remaining Capacity (GB)",
              "Capacity (GB)",
              "Status",
              "Attribute",
              "Type",
            ].map((h) => (
              <TableHead
                key={h}
                className="h-8 px-2.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground whitespace-nowrap"
              >
                {h}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {disks.map((disk) => {
            const label = disk.health_label || disk.status || "Unknown"
            return (
              <TableRow key={`${disk.disk_number}-${disk.name}`} className="hover:bg-muted/40">
                <TableCell className="px-2.5 py-2 text-sm font-medium tabular-nums">
                  {disk.disk_number}
                </TableCell>
                <TableCell className="px-2.5 py-2 text-sm tabular-nums">
                  {disk.remaining_gb != null ? disk.remaining_gb : "—"}
                </TableCell>
                <TableCell className="px-2.5 py-2 text-sm tabular-nums">
                  {disk.capacity_gb != null ? disk.capacity_gb : "—"}
                </TableCell>
                <TableCell className="px-2.5 py-2">
                  <Badge
                    className={cn("border font-medium", hddStatusTone(label))}
                    variant="outline"
                  >
                    <span
                      className={cn(
                        "mr-1.5 inline-block h-1.5 w-1.5 shrink-0 rounded-full",
                        hddStatusDot(label),
                      )}
                    />
                    {label}
                  </Badge>
                </TableCell>
                <TableCell className="px-2.5 py-2 text-sm whitespace-nowrap">
                  {disk.attribute || "—"}
                </TableCell>
                <TableCell className="px-2.5 py-2 text-sm text-muted-foreground whitespace-nowrap">
                  {disk.disk_type || "—"}
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}
