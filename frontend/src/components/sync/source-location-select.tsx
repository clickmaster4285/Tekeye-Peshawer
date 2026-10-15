import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { ALL_SOURCE_LOCATIONS, type SourceLocationOption } from "@/lib/source-location"

export function SourceLocationSelect({
  value,
  onChange,
  options,
  className = "w-full sm:w-48",
}: {
  value: string
  onChange: (value: string) => void
  options: SourceLocationOption[]
  className?: string
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className={className} aria-label="Location">
        <SelectValue placeholder="Location" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL_SOURCE_LOCATIONS}>All locations</SelectItem>
        {options.map((o) => (
          <SelectItem key={o.code} value={o.code}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
