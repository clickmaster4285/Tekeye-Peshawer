import { useEffect, useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Check, ChevronsUpDown, Loader2, Search } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandItem,
  CommandList,
} from "@/components/ui/command"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  createStaffUser,
  fetchStaffLoginPreview,
  fetchUnlinkedEmployees,
  type StaffLoginPreview,
} from "@/lib/staff-api"
import { cn } from "@/lib/utils"
import { LOCATION_OPTIONS, ROLE_OPTIONS } from "@/lib/users-api"

function slugLoginId(raw: string): string {
  return raw.replace(/[^A-Za-z0-9._-]+/g, "").toUpperCase().slice(0, 40)
}

export function CreateEmployeeLoginForm({
  staffId,
  allowSelectEmployee = false,
  onSuccess,
  onCancel,
}: {
  staffId?: number
  allowSelectEmployee?: boolean
  onSuccess: (loginId: string, staffName: string) => void
  onCancel?: () => void
}) {
  const [selectedId, setSelectedId] = useState<number | undefined>(staffId)
  const [password, setPassword] = useState("")
  const [role, setRole] = useState("")
  const [location, setLocation] = useState("")
  const [username, setUsername] = useState("")
  const [usernameEdited, setUsernameEdited] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [searchInput, setSearchInput] = useState("")
  const [debouncedSearch, setDebouncedSearch] = useState("")

  useEffect(() => {
    setSelectedId(staffId)
    setUsernameEdited(false)
  }, [staffId])

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedSearch(searchInput.trim()), 300)
    return () => window.clearTimeout(t)
  }, [searchInput])

  const canSearch = debouncedSearch.length >= 2
  const employeesQuery = useQuery({
    queryKey: ["staff", "unlinked", debouncedSearch],
    queryFn: () => fetchUnlinkedEmployees(debouncedSearch),
    enabled: allowSelectEmployee && canSearch,
  })

  const previewQuery = useQuery({
    queryKey: ["staff", selectedId, "login-preview"],
    queryFn: () => fetchStaffLoginPreview(selectedId!),
    enabled: Number.isInteger(selectedId),
  })

  const preview: StaffLoginPreview | undefined = previewQuery.data
  const showRole = Boolean(preview?.role_required)
  const showLocation = Boolean(preview?.location_required) || (showRole && role !== "ADMIN" && role !== "")

  useEffect(() => {
    if (!preview?.username || usernameEdited) return
    setUsername(preview.username)
  }, [preview?.username, usernameEdited])

  const employeeOptions = useMemo(() => {
    const rows = (employeesQuery.data ?? []).slice(0, 50)
    return rows.map((row) => ({
      id: row.id,
      name: row.full_name,
      label: `${row.full_name}${row.personal_number ? ` · ${row.personal_number}` : row.employee_id ? ` · ${row.employee_id}` : ""}`,
    }))
  }, [employeesQuery.data])

  const selectedLabel = employeeOptions.find((row) => row.id === selectedId)?.label
    || preview?.staff_name
    || (selectedId ? `Employee #${selectedId}` : "")

  async function submit() {
    setError(null)
    if (!selectedId) {
      setError("Select an employee.")
      return
    }
    const loginId = slugLoginId(username)
    if (loginId.length < 3) {
      setError("User ID must be at least 3 letters or numbers, based on the employee name.")
      return
    }
    if (password.length < 6) {
      setError("Password must be at least 6 characters.")
      return
    }
    if (showRole && !role) {
      setError("Select a role. This employee does not have a system role yet.")
      return
    }
    if ((preview?.location_required || (showRole && role && role !== "ADMIN")) && !location && !preview?.location) {
      setError("Select a location. This employee does not have a posting location yet.")
      return
    }
    setSaving(true)
    try {
      const result = await createStaffUser(selectedId, {
        password,
        username: loginId,
        role: role || preview?.role || undefined,
        location: location || preview?.location || undefined,
      })
      onSuccess(result.login_id, preview?.staff_name || "Employee")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create login")
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      {allowSelectEmployee ? (
        <div className="space-y-2">
          <Label>Search employee</Label>
          <Popover open={pickerOpen} onOpenChange={setPickerOpen}>
            <PopoverTrigger asChild>
              <Button
                type="button"
                variant="outline"
                role="combobox"
                aria-expanded={pickerOpen}
                className="w-full justify-between font-normal"
              >
                <span className="truncate">
                  {selectedLabel || "Search by name, CNIC, or employee ID"}
                </span>
                <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-0" align="start">
              <Command shouldFilter={false}>
                <div className="flex items-center border-b px-3">
                  <Search className="mr-2 h-4 w-4 shrink-0 opacity-50" />
                  <input
                    value={searchInput}
                    onChange={(e) => setSearchInput(e.target.value)}
                    placeholder="Type at least 2 letters…"
                    className="placeholder:text-muted-foreground flex h-10 w-full bg-transparent py-3 text-sm outline-none"
                  />
                </div>
                <CommandList>
                  {!canSearch ? (
                    <p className="px-3 py-6 text-center text-sm text-muted-foreground">
                      Type a name to search the employee list.
                    </p>
                  ) : employeesQuery.isFetching ? (
                    <p className="flex items-center justify-center gap-2 px-3 py-6 text-sm text-muted-foreground">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Searching…
                    </p>
                  ) : (
                    <>
                      <CommandEmpty>No unmatched employees found.</CommandEmpty>
                      <CommandGroup>
                        {employeeOptions.map((row) => (
                          <CommandItem
                            key={row.id}
                            value={String(row.id)}
                            onSelect={() => {
                              setSelectedId(row.id)
                              setRole("")
                              setLocation("")
                              setUsernameEdited(false)
                              setPickerOpen(false)
                            }}
                          >
                            <Check className={cn("h-4 w-4", selectedId === row.id ? "opacity-100" : "opacity-0")} />
                            {row.label}
                          </CommandItem>
                        ))}
                      </CommandGroup>
                    </>
                  )}
                </CommandList>
              </Command>
            </PopoverContent>
          </Popover>
        </div>
      ) : null}

      {previewQuery.isLoading ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Generating user ID from name…
        </p>
      ) : null}

      {preview?.already_linked ? (
        <p className="text-sm text-amber-700">This employee already has a linked user account.</p>
      ) : null}

      {preview && !preview.already_linked ? (
        <>
          <div className="rounded-md border bg-muted/40 p-3 text-sm space-y-1">
            <p><span className="text-muted-foreground">Name:</span> {preview.staff_name}</p>
            {preview.designation ? (
              <p><span className="text-muted-foreground">Designation:</span> {preview.designation}</p>
            ) : null}
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <Label htmlFor="emp-login-username">User ID *</Label>
              {usernameEdited && preview.username ? (
                <button
                  type="button"
                  className="text-xs text-primary hover:underline"
                  onClick={() => {
                    setUsername(preview.username)
                    setUsernameEdited(false)
                  }}
                >
                  Reset to name
                </button>
              ) : null}
            </div>
            <Input
              id="emp-login-username"
              value={username}
              onChange={(e) => {
                setUsername(slugLoginId(e.target.value))
                setUsernameEdited(true)
              }}
              placeholder="Generated from employee name"
              autoComplete="off"
            />
            <p className="text-xs text-muted-foreground">
              Suggested from the employee name (e.g. Umar Farooq → UMARFAROOQ). You can edit it before creating the login.
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="emp-login-password">Password *</Label>
            <Input
              id="emp-login-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Minimum 6 characters"
              autoComplete="new-password"
            />
          </div>

          {showRole ? (
            <div className="space-y-2">
              <Label>Role *</Label>
              <Select value={role} onValueChange={setRole}>
                <SelectTrigger>
                  <SelectValue placeholder="This employee has no system role yet" />
                </SelectTrigger>
                <SelectContent>
                  {ROLE_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : preview.role ? (
            <p className="text-sm text-muted-foreground">Role from employee: {preview.role.replace(/_/g, " ")}</p>
          ) : null}

          {showLocation && role !== "ADMIN" ? (
            <div className="space-y-2">
              <Label>Location *</Label>
              <Select value={location} onValueChange={setLocation}>
                <SelectTrigger>
                  <SelectValue placeholder="Select office location" />
                </SelectTrigger>
                <SelectContent>
                  {LOCATION_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : preview.location ? (
            <p className="text-sm text-muted-foreground">Location from employee: {preview.location.replace(/_/g, " ")}</p>
          ) : null}
        </>
      ) : null}

      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      <div className="flex justify-end gap-2">
        {onCancel ? (
          <Button type="button" variant="outline" onClick={onCancel} disabled={saving}>
            Cancel
          </Button>
        ) : null}
        <Button type="button" onClick={() => void submit()} disabled={saving || !selectedId || preview?.already_linked}>
          {saving ? "Creating…" : "Create login"}
        </Button>
      </div>
    </div>
  )
}
