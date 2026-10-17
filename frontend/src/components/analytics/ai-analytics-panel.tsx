import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { AnalyticsData } from "@/lib/analytics-api"
import { CHART_INK, SERIES, SINGLE } from "./palette"

const axis = { stroke: CHART_INK.axis, fontSize: 11, tickLine: false, axisLine: false }
const tooltipStyle = { fontSize: 12, borderRadius: 8, border: `1px solid ${CHART_INK.grid}` }
const grid = <CartesianGrid stroke={CHART_INK.grid} vertical={false} />
const fmt = (v: number) => v.toLocaleString()

function Panel({ title, note, children, height = 220 }: { title: string; note?: string; children: React.ReactNode; height?: number }) {
  return (
    <div className="rounded-lg border border-border p-3">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <p className="text-sm font-medium text-foreground">{title}</p>
        {note && <span className="text-[11px] text-muted-foreground">{note}</span>}
      </div>
      <div style={{ height }}>{children}</div>
    </div>
  )
}

function Empty() {
  return <div className="flex h-full items-center justify-center text-xs text-muted-foreground">No detections in this range</div>
}

/** Horizontal bars: label on the left, value on hover and at the bar end. */
function RankBars({ rows, name }: { rows: { label: string; count: number }[]; name: string }) {
  if (!rows.length) return <Empty />
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={rows} layout="vertical" margin={{ left: 4, right: 36, top: 4, bottom: 4 }}>
        <XAxis type="number" hide />
        <YAxis type="category" dataKey="label" width={120} {...axis} tick={{ fill: CHART_INK.text, fontSize: 11 }} />
        <Tooltip cursor={{ fill: "rgba(0,0,0,0.04)" }} contentStyle={tooltipStyle} formatter={(v: number) => [fmt(v), name]} />
        <Bar
          dataKey="count"
          fill={SINGLE}
          radius={[0, 4, 4, 0]}
          barSize={14}
          label={{ position: "right", fontSize: 11, fill: CHART_INK.text, formatter: fmt }}
        />
      </BarChart>
    </ResponsiveContainer>
  )
}

function ColumnBars({ rows, name }: { rows: { label: string; count: number }[]; name: string }) {
  if (!rows.some((r) => r.count)) return <Empty />
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={rows} margin={{ left: 0, right: 8, top: 8, bottom: 0 }} barCategoryGap={2}>
        {grid}
        <XAxis dataKey="label" {...axis} interval="preserveStartEnd" />
        <YAxis {...axis} width={44} tickFormatter={fmt} />
        <Tooltip cursor={{ fill: "rgba(0,0,0,0.04)" }} contentStyle={tooltipStyle} formatter={(v: number) => [fmt(v), name]} />
        <Bar dataKey="count" fill={SINGLE} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

/** Detection analytics for the selected location and range — all from real detection logs. */
export function AiAnalyticsPanel({ data, rangeLabel }: { data?: AnalyticsData; rangeLabel: string }) {
  const byClass = (data?.by_class ?? []).map((r) => ({ label: r.name, count: r.count }))
  const topCams = (data?.top_alert_cameras ?? []).map((r) => ({ label: `${r.camera} · ${r.location}`, count: r.count }))
  const overTime = data?.over_time ?? []
  const hasTrend = overTime.some((r) => r.people || r.vehicles || r.weapons || r.plates)
  const bucket = data?.range.bucket === "hour" ? "per hour" : "per day"

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">AI detection analytics</CardTitle>
        <p className="text-xs text-muted-foreground">{rangeLabel}</p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Panel title="Detections by object type" note="Top 8 + other">
            <RankBars rows={byClass} name="Detections" />
          </Panel>
          <Panel title="Top alert cameras" note="Weapons + AI alerts">
            <RankBars rows={topCams} name="Alerts" />
          </Panel>
        </div>

        <Panel title="Detections over time" note={bucket} height={260}>
          {!hasTrend ? (
            <Empty />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={overTime} margin={{ left: 0, right: 12, top: 8, bottom: 0 }}>
                {grid}
                <XAxis dataKey="label" {...axis} interval="preserveStartEnd" />
                <YAxis {...axis} width={48} tickFormatter={fmt} />
                <Tooltip contentStyle={tooltipStyle} formatter={(v: number, n: string) => [fmt(v), n]} />
                <Legend iconType="plainline" wrapperStyle={{ fontSize: 12, color: CHART_INK.text }} />
                {SERIES.map((s) => (
                  <Line
                    key={s.key}
                    type="monotone"
                    dataKey={s.key}
                    name={s.label}
                    stroke={s.color}
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4 }}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          )}
        </Panel>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <Panel title="Activity by hour of day">
            <ColumnBars rows={data?.activity_by_hour ?? []} name="Detections" />
          </Panel>
          <Panel title="Activity by weekday">
            <ColumnBars rows={data?.activity_by_weekday ?? []} name="Detections" />
          </Panel>
          <Panel title="Model confidence trend" note="Average detection confidence">
            {!data?.confidence_trend.length ? (
              <Empty />
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data.confidence_trend} margin={{ left: 0, right: 12, top: 8, bottom: 0 }}>
                  {grid}
                  <XAxis dataKey="label" {...axis} interval="preserveStartEnd" />
                  <YAxis {...axis} width={40} domain={[0, 100]} tickFormatter={(v: number) => `${v}%`} />
                  <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => [`${v}%`, "Avg confidence"]} />
                  <Line type="monotone" dataKey="avg_confidence" stroke={SINGLE} strokeWidth={2} dot={{ r: 4 }} />
                </LineChart>
              </ResponsiveContainer>
            )}
          </Panel>
        </div>
      </CardContent>
    </Card>
  )
}
