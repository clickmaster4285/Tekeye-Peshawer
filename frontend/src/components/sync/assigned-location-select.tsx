import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { useSourceLocations } from "@/lib/source-location"

/**
 * "Works at" — which server a staff member belongs to (Stage 4). Choosing a city sends the
 * record and its face data there; changing it later transfers them. Super Admin at HQ only.
 */
export function AssignedLocationSelect({
  value,
  initial,
  onChange,
}: {
  value: string | null | undefined
  /** Saved location when editing; a different choice is a transfer. */
  initial?: string | null
  onChange: (code: string) => void
}) {
  const locations = useSourceLocations()
  if (!locations.enabled) return null

  const hqCode = locations.options[0]?.code ?? ""
  const current = value || hqCode
  const saved = initial || hqCode
  const transferring = initial !== undefined && current !== saved

  return (
    <div className="bg-card rounded-xl border border-border shadow-sm p-4 sm:p-6 mt-6 grid gap-2 sm:max-w-md">
      <Label htmlFor="assigned-location">Works at</Label>
      <Select value={current} onValueChange={onChange}>
        <SelectTrigger id="assigned-location">
          <SelectValue placeholder="Location" />
        </SelectTrigger>
        <SelectContent>
          {locations.options.map((o) => (
            <SelectItem key={o.code} value={o.code}>
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <p className={`text-xs ${transferring ? "text-amber-600" : "text-muted-foreground"}`}>
        {transferring
          ? `Transfer: the record and face data move from ${locations.labelFor(saved)} to ${locations.labelFor(current)} on save.`
          : current === hqCode
            ? "Recognized by this office's cameras."
            : "Sent to that city with face data; recognized by its cameras only."}
      </p>
    </div>
  )
}
