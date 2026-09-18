import { Switch } from "@/components/ui/switch"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useState } from "react"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { LOCATION_OPTIONS, inferLocationCode } from "@/lib/locations"

export type AddStaffStep3Form = {
  has_login?: boolean
  login_username?: string
  password?: string
  role?: string
  location?: string
  current_posting?: string
  branch_location?: string
  city?: string
}

export function AddStaffStep3LoginAccess({
  form,
  updateForm,
  onCancel,
  onReset,
  onPrevious,
  onFinish,
  submitting,
  mode = "create",
  hasExistingLogin = false,
  generatedLoginId,
}: {
  form: AddStaffStep3Form
  updateForm: (patch: Partial<AddStaffStep3Form>) => void
  onCancel: () => void
  onReset: () => void
  onPrevious: () => void
  onFinish: () => void
  submitting: boolean
  mode?: "create" | "edit"
  hasExistingLogin?: boolean
  generatedLoginId?: string
}) {
  const [errors, setErrors] = useState<{ password?: string; location?: string }>({})
  const inferredLocation =
    form.location || inferLocationCode(form.branch_location, form.current_posting, form.city)
  const needsLocation = Boolean(form.has_login) && form.role !== "ADMIN" && !inferredLocation

  const validateForm = (): boolean => {
    if (!form.has_login) {
      return true
    }

    const newErrors: { password?: string; location?: string } = {}

    if (!form.password?.trim()) {
      if (!(mode === "edit" && hasExistingLogin)) {
        newErrors.password = "Password is required"
      }
    } else if (form.password.length < 6) {
      newErrors.password = "Password must be at least 6 characters"
    }

    if (needsLocation && !(mode === "edit" && hasExistingLogin)) {
      newErrors.location = "Location is required because this employee has no posting location yet"
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleFinish = () => {
    if (validateForm()) {
      onFinish()
    }
  }

  return (
    <div className="space-y-8">
      <Label className="text-[22px] font-bold text-foreground">Login Access</Label>

      <div className="space-y-3 border-t border-border pt-6">
        <div className="rounded-lg border-2 border-dashed border-muted-foreground/30 bg-muted/20 p-6 transition-colors hover:border-primary/40 hover:bg-muted/30">
          <div className="flex items-center justify-between gap-4">
            <div className="min-w-0">
              <p className="text-base font-medium text-foreground">Give this employee login access?</p>
              <p className="text-sm text-muted-foreground">
                {mode === "edit" && hasExistingLogin
                  ? "Leave password blank to keep the current password. Enter a new one only to change it."
                  : "If enabled, a unique login ID is generated from this employee’s name. You can edit it, then set a password."}
              </p>
            </div>
            <Switch
              checked={Boolean(form.has_login)}
              onCheckedChange={(checked) => {
                updateForm({ has_login: checked })
                setErrors({})
              }}
              className="data-[state=checked]:bg-[#3366FF]"
            />
          </div>

          {form.has_login ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-6">
              <div className="space-y-2">
                <Label className="text-base text-foreground">Unique login ID</Label>
                <Input
                  readOnly
                  value={
                    hasExistingLogin
                      ? form.login_username || ""
                      : generatedLoginId || form.login_username || "Generated after save from Personal No. / Employee ID"
                  }
                  className="h-10 text-base bg-muted border-border"
                />
                <p className="text-sm text-muted-foreground">
                  Generated from the employee record. Do not invent a username.
                </p>
              </div>
              <div className="space-y-2">
                <Label className="text-base text-foreground">
                  Password
                  {form.has_login && !(mode === "edit" && hasExistingLogin) && (
                    <span className="text-destructive ml-1">*</span>
                  )}
                </Label>
                <Input
                  type="password"
                  placeholder={mode === "edit" && hasExistingLogin ? "Leave blank to keep current" : "Enter password"}
                  value={form.password || ""}
                  onChange={(e) => {
                    updateForm({ password: e.target.value })
                    if (errors.password) {
                      setErrors({ ...errors, password: undefined })
                    }
                  }}
                  className={`h-10 text-base bg-background border-border ${errors.password ? "border-destructive" : ""}`}
                />
                {errors.password ? (
                  <p className="text-sm text-destructive">{errors.password}</p>
                ) : (
                  <p className="text-sm text-muted-foreground">(Minimum 6 characters)</p>
                )}
              </div>
              {form.role ? (
                <p className="text-sm text-muted-foreground md:col-span-2">
                  Role from employee: {form.role.replace(/_/g, " ")}
                </p>
              ) : null}
              {!needsLocation && inferredLocation && form.role !== "ADMIN" ? (
                <p className="text-sm text-muted-foreground md:col-span-2">
                  Location from employee: {inferredLocation.replace(/_/g, " ")}
                </p>
              ) : null}
              {needsLocation ? (
                <div className="space-y-2 md:col-span-2">
                  <Label className="text-base text-foreground">
                    Location <span className="text-destructive">*</span>
                  </Label>
                  <Select
                    value={form.location || ""}
                    onValueChange={(value) => {
                      updateForm({ location: value })
                      if (errors.location) setErrors({ ...errors, location: undefined })
                    }}
                  >
                    <SelectTrigger className={errors.location ? "border-destructive" : ""}>
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
                  {errors.location ? (
                    <p className="text-sm text-destructive">{errors.location}</p>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      Required because this employee does not have a posting location yet.
                    </p>
                  )}
                </div>
              ) : null}
            </div>
          ) : (
            <div className="mt-4 text-sm text-muted-foreground bg-white/50 p-3 rounded-md border border-border">
              {mode === "edit"
                ? "This employee will be saved without login access changes."
                : "This employee will be created without login access."}
            </div>
          )}
        </div>
      </div>

      {/* Action buttons matching the previous design */}
      <div className="flex flex-col-reverse sm:flex-row sm:items-center sm:justify-between gap-4 pt-6 border-t border-border">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-[#CCCCCC] bg-white px-4 py-2.5 text-base font-normal text-[#3366CC] transition-colors hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => {
              onReset()
              setErrors({})
            }}
            className="rounded-md border border-[#CCCCCC] bg-white px-4 py-2.5 text-base font-normal text-[#3366CC] transition-colors hover:bg-gray-50"
          >
            Reset Form
          </button>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onPrevious}
            className="rounded-md bg-[#3366FF] px-4 py-2.5 text-base font-normal text-white transition-colors hover:bg-[#2952CC]"
          >
            Previous
          </button>
          <button
            type="button"
            onClick={handleFinish}
            disabled={submitting}
            className="shrink-0 rounded-md bg-[#3366FF] px-5 py-2.5 text-base font-normal text-white transition-colors hover:bg-[#2952CC] disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {submitting
              ? mode === "edit"
                ? "Saving…"
                : "Adding Staff..."
              : mode === "edit"
                ? "Save changes"
                : "Add Staff"}
          </button>
        </div>
      </div>
    </div>
  )
}