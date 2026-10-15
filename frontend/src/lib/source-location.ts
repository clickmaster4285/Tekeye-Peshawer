/**
 * "Which server did this record come from?" — Location filter for HQ pages (Stage 3).
 * Options come from Locations & Sync; only the Super Admin on the head office gets them.
 */
import { useMemo } from "react"
import { useQuery } from "@tanstack/react-query"
import { getStoredUser } from "@/lib/auth"
import { normalizeRole } from "@/lib/role-access"
import { fetchSyncSites } from "@/lib/sync-sites-api"

export const ALL_SOURCE_LOCATIONS = "ALL"

export type SourceLocationOption = { code: string; label: string }

export function useSourceLocations() {
  const isAdmin = normalizeRole(getStoredUser()?.role) === "ADMIN"
  const { data } = useQuery({
    queryKey: ["sync-sites"],
    queryFn: fetchSyncSites,
    enabled: isAdmin,
    staleTime: 60_000,
    retry: false,
  })

  return useMemo(() => {
    const hqCode = data?.hq.location_code ?? ""
    const options: SourceLocationOption[] = data
      ? [
          { code: hqCode, label: `${hqCode.charAt(0)}${hqCode.slice(1).toLowerCase()} (head office)` },
          ...data.sites.map((s) => ({ code: s.location_code, label: s.name })),
        ]
      : []
    const labels = new Map(options.map((o) => [o.code, o.label]))
    return {
      /** Show the filter and Location column only when there is at least one city. */
      enabled: Boolean(data && data.sites.length > 0),
      options,
      /** Untagged rows are this server's own. */
      labelFor: (code: string | null | undefined) => labels.get(code || hqCode) ?? code ?? hqCode,
      matches: (code: string | null | undefined, selected: string) =>
        selected === ALL_SOURCE_LOCATIONS || (code || hqCode) === selected,
      /** This server's own record (not a copy from a city). True for everything until the sites load. */
      isLocal: (code: string | null | undefined) => !hqCode || !code || code === hqCode,
    }
  }, [data])
}
