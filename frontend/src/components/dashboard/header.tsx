import { memo, useCallback, useEffect, useState, startTransition } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { Search, Bell, HelpCircle, User, LogOut, Menu, Wifi, WifiOff } from "lucide-react"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Switch } from "@/components/ui/switch"
import { clearAuth, getStoredUser, isAuthenticated, AUTH_USER_UPDATED_EVENT } from "@/lib/auth"
import { stopOfficerGpsTracking } from "@/lib/officer-gps-session"
import { queryClient } from "@/lib/query-client"
import { clearLegacyVmsLocalStorage } from "@/lib/vms-list-api"
import { getRoleDisplayLabel, normalizeRole } from "@/lib/role-access"
import { isGlobalAdmin } from "@/lib/location-access"
import { locationLabel } from "@/lib/locations"
import {
  canSeeAllCitiesCameras,
  canViewAllCitiesCameras,
  getCamerasWallLabel,
  setAllCitiesCamerasPreference,
} from "@/lib/all-cities-cameras"
import { listRemoteServers, type RemoteServerRecord } from "@/lib/ops-central-api"
import {
  ROUTES,
  getSeizureMgmtAssessmentDetailPath,
  getSeizureMgmtNoteSheetDetailPath,
  getSeizureMgmtRecoveryMemoDetailPath,
} from "@/routes/config"
import {
  fetchNoteSheetNotifications,
  markAllNoteSheetNotificationsRead,
  markNoteSheetNotificationRead,
  type NoteSheetNotificationItem,
} from "@/lib/seizure-management-api"
import { cn } from "@/lib/utils"
import { REALTIME_INVALIDATE_EVENT } from "@/lib/realtime-socket"

interface HeaderProps {
  onMenuClick?: () => void
}

export const Header = memo(function Header({ onMenuClick }: HeaderProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const [user, setUser] = useState(() => getStoredUser())
  useEffect(() => {
    const sync = () => setUser(getStoredUser())
    window.addEventListener(AUTH_USER_UPDATED_EVENT, sync)
    return () => window.removeEventListener(AUTH_USER_UPDATED_EVENT, sync)
  }, [])
  const role = normalizeRole(user?.role)
  const showAllCitiesToggle = canViewAllCitiesCameras(user?.role)
  const camerasWallLabel = getCamerasWallLabel(user?.role, user?.location)
  const showAllCityServerChips = canSeeAllCitiesCameras(user?.role, user?.location)
  const [searchInput, setSearchInput] = useState("")
  const [notifications, setNotifications] = useState<NoteSheetNotificationItem[]>([])
  const [unreadCount, setUnreadCount] = useState(0)
  const [notifOpen, setNotifOpen] = useState(false)
  const [connectedServers, setConnectedServers] = useState<RemoteServerRecord[]>([])

  const allCitiesCameras = location.pathname === ROUTES.ALL_CITIES_CAMERAS

  const navigateAfterPaint = useCallback(
    (to: string, options?: { replace?: boolean }) => {
      // Defer soft navigation one frame so Chrome DevTools web-vitals (VMxx reportAllChanges)
      // does not race MJPEG teardown during All Cities toggle.
      requestAnimationFrame(() => {
        startTransition(() => {
          navigate(to, options)
        })
      })
    },
    [navigate],
  )

  const handleAllCitiesCameras = useCallback(
    (enabled: boolean) => {
      if (enabled) {
        setAllCitiesCamerasPreference(true)
        navigateAfterPaint(ROUTES.ALL_CITIES_CAMERAS)
        return
      }
      setAllCitiesCamerasPreference(false)
      if (location.pathname === ROUTES.ALL_CITIES_CAMERAS) {
        navigateAfterPaint(
          role === "IT_SUPERADMIN" ? ROUTES.OPS_CENTRAL : ROUTES.DASHBOARD,
          { replace: true },
        )
      }
    },
    [location.pathname, navigateAfterPaint, role],
  )

  useEffect(() => {
    if (!showAllCitiesToggle || !isAuthenticated()) {
      setConnectedServers([])
      return
    }
    let cancelled = false
    const load = () => {
      listRemoteServers()
        .then((rows) => {
          if (!cancelled) setConnectedServers(rows.filter((s) => s.is_active))
        })
        .catch(() => {
          if (!cancelled) setConnectedServers([])
        })
    }
    load()
    const onRealtime = (e: Event) => {
      const domains = (e as CustomEvent<{ domains?: string[] }>).detail?.domains || []
      if (domains.some((d) => ["ops", "cameras"].includes(d))) load()
    }
    window.addEventListener(REALTIME_INVALIDATE_EVENT, onRealtime)
    return () => {
      cancelled = true
      window.removeEventListener(REALTIME_INVALIDATE_EVENT, onRealtime)
    }
  }, [showAllCitiesToggle])

  useEffect(() => {
    if (location.pathname === ROUTES.ALL_CITIES_CAMERAS) {
      setAllCitiesCamerasPreference(true)
    }
  }, [location.pathname])

  const loadNotifications = useCallback(() => {
    if (!isAuthenticated()) return
    if (typeof document !== "undefined" && document.visibilityState === "hidden") return
    fetchNoteSheetNotifications()
      .then((data) => {
        setNotifications(data.results || [])
        setUnreadCount(data.unreadCount || 0)
      })
      .catch(() => {
        setNotifications([])
        setUnreadCount(0)
      })
  }, [])

  useEffect(() => {
    loadNotifications()
    const onRealtime = (e: Event) => {
      const domains = (e as CustomEvent<{ domains?: string[] }>).detail?.domains || []
      if (domains.some((d) => ["notifications", "seizure", "vms"].includes(d))) {
        if (document.visibilityState === "visible") loadNotifications()
      }
    }
    const onVisibility = () => {
      if (document.visibilityState === "visible") loadNotifications()
    }
    window.addEventListener(REALTIME_INVALIDATE_EVENT, onRealtime)
    document.addEventListener("visibilitychange", onVisibility)
    return () => {
      window.removeEventListener(REALTIME_INVALIDATE_EVENT, onRealtime)
      document.removeEventListener("visibilitychange", onVisibility)
    }
  }, [loadNotifications])

  const handleLogout = async () => {
    await stopOfficerGpsTracking({ endDuty: true })
    clearAuth()
    queryClient.clear()
    clearLegacyVmsLocalStorage()
    navigate(ROUTES.LOGIN, { replace: true })
  }

  const openNotification = async (n: NoteSheetNotificationItem) => {
    try {
      if (!n.isRead) await markNoteSheetNotificationRead(n.id)
    } catch {
      /* ignore */
    }
    setNotifOpen(false)
    loadNotifications()
    if (n.hrefKind === "recovery" || n.recoveryMemoId) {
      if (n.recoveryMemoId) navigate(getSeizureMgmtRecoveryMemoDetailPath(n.recoveryMemoId))
      return
    }
    if (n.hrefKind === "assessment" || n.assessmentId) {
      if (n.assessmentId) navigate(getSeizureMgmtAssessmentDetailPath(n.assessmentId))
      return
    }
    if (n.noteSheetId) {
      navigate(getSeizureMgmtNoteSheetDetailPath(n.noteSheetId))
    }
  }

  const markAllRead = async () => {
    try {
      await markAllNoteSheetNotificationsRead()
      loadNotifications()
    } catch {
      /* ignore */
    }
  }

  const displayName = user?.full_name?.trim() || user?.username?.trim() || "User"
  const roleLabel = getRoleDisplayLabel(user?.role)
  const locationName = user?.location
    ? locationLabel(user.location)
    : isGlobalAdmin(user?.role)
      ? "All Locations"
      : ""
  const roleLine = locationName ? `${roleLabel} · ${locationName}` : roleLabel
  const initials = displayName
    .split(" ")
    .map((n) => n[0])
    .join("")
    .slice(0, 2)
    .toUpperCase()

  return (
    <header className="fixed left-0 right-0 top-0 z-20 flex min-h-14 min-w-0 shrink-0 flex-wrap items-center gap-x-1.5 gap-y-1.5 border-b border-gray-100 bg-white px-2 py-2 sm:min-h-16 sm:gap-x-2 sm:px-3 sm:py-2 md:left-[240px] md:gap-x-2 lg:left-[280px] lg:px-4 xl:left-[333px] xl:flex-nowrap xl:gap-x-4 xl:px-8 xl:py-0">
      {/* Left: menu + search */}
      <div className="flex min-w-0 flex-1 basis-[min(100%,12rem)] items-center gap-1.5 sm:gap-2 md:max-w-[10rem] lg:max-w-[14rem] xl:max-w-[452px]">
        <button
          type="button"
          className="inline-flex shrink-0 rounded-lg p-2 text-gray-600 hover:bg-gray-100 md:hidden"
          onClick={onMenuClick}
          aria-label="Open menu"
        >
          <Menu className="h-5 w-5" />
        </button>
        <div className="flex min-w-0 flex-1 items-center rounded-[10px] border border-gray-200 bg-white py-1.5 pl-2 pr-2 sm:py-2 sm:pl-3 md:pl-3 xl:pl-4 xl:pr-3.5">
          <Search className="h-4 w-4 shrink-0 text-gray-400 sm:h-5 sm:w-5" />
          <input
            type="text"
            placeholder="Search..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            aria-label="Search visitors, pass IDs"
            className="ml-1.5 min-w-0 flex-1 border-0 bg-transparent py-1 text-sm text-[#4A5565] outline-none placeholder:text-gray-400 sm:ml-2 sm:text-[15px] xl:placeholder:opacity-100"
          />
        </div>
      </div>

      {/* Center: All Cities toggle + ML chips */}
      {showAllCitiesToggle && (
        <div className="order-3 flex w-full min-w-0 flex-col items-center justify-center gap-1 px-0 sm:order-none sm:w-auto sm:max-w-none sm:shrink-0 md:order-none md:mx-auto md:w-auto xl:px-2">
          <div className="flex items-center gap-1.5 sm:gap-2">
            <Switch
              id="all-cities-cameras"
              checked={allCitiesCameras}
              onCheckedChange={handleAllCitiesCameras}
              aria-label={camerasWallLabel}
              className="h-6 w-11 shrink-0 xl:h-7 xl:w-12 [&_[data-slot=switch-thumb]]:size-5 xl:[&_[data-slot=switch-thumb]]:size-6 [&_[data-slot=switch-thumb]]:data-[state=checked]:translate-x-[1.2rem] xl:[&_[data-slot=switch-thumb]]:data-[state=checked]:translate-x-[1.35rem]"
            />
            <span
              role="button"
              tabIndex={0}
              onClick={() => handleAllCitiesCameras(!allCitiesCameras)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault()
                  handleAllCitiesCameras(!allCitiesCameras)
                }
              }}
              className="cursor-pointer select-none text-xs font-semibold text-[#101727] sm:text-sm xl:text-base"
              title={camerasWallLabel}
            >
              <span className="hidden whitespace-nowrap xl:inline">{camerasWallLabel}</span>
              <span className="inline whitespace-nowrap xl:hidden">Cameras</span>
            </span>
          </div>
          {showAllCityServerChips && connectedServers.length > 0 && (
            <div className="hidden max-w-full flex-wrap items-center justify-center gap-1 lg:flex">
              {connectedServers.slice(0, 6).map((s) => {
                const health = (s.last_health || "").toLowerCase()
                const healthy =
                  health === "ok" ||
                  health === "online" ||
                  health === "healthy" ||
                  health === "up"
                return (
                  <span
                    key={s.id}
                    title={s.ml_base_url || s.base_url || s.name}
                    className={cn(
                      "inline-flex max-w-[5.5rem] items-center gap-0.5 truncate rounded-full border px-1.5 py-0.5 text-[10px] font-medium xl:max-w-[7.5rem]",
                      healthy
                        ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                        : "border-amber-200 bg-amber-50 text-amber-900",
                    )}
                  >
                    {healthy ? (
                      <Wifi className="h-2.5 w-2.5 shrink-0" />
                    ) : (
                      <WifiOff className="h-2.5 w-2.5 shrink-0" />
                    )}
                    <span className="truncate">{s.name}</span>
                  </span>
                )
              })}
              {connectedServers.length > 6 && (
                <span className="text-[10px] text-muted-foreground">
                  +{connectedServers.length - 6}
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {/* Right: notifications, help, profile */}
      <div className="ml-auto flex min-w-0 shrink-0 items-center justify-end gap-0.5 sm:gap-1">
        <div className="flex shrink-0 items-center gap-0.5">
          <DropdownMenu
            open={notifOpen}
            onOpenChange={(open) => {
              setNotifOpen(open)
              if (open) loadNotifications()
            }}
          >
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="relative rounded-lg p-1.5 text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-700 sm:p-2"
                aria-label="Notifications"
              >
                <Bell className="h-5 w-5 sm:h-6 sm:w-6" />
                {unreadCount > 0 && (
                  <span
                    className="absolute right-1 top-1 h-2 w-2 min-w-[0.5rem] rounded-full bg-red-500 ring-2 ring-white sm:right-1.5 sm:top-1.5"
                    aria-hidden
                  />
                )}
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="end"
              className="w-[min(360px,calc(100vw-1.5rem))] max-h-[min(420px,70vh)] overflow-y-auto p-0"
            >
              <div className="flex items-center justify-between px-3 py-2">
                <DropdownMenuLabel className="p-0">Notifications</DropdownMenuLabel>
                {unreadCount > 0 && (
                  <button
                    type="button"
                    className="text-xs text-primary hover:underline"
                    onClick={() => void markAllRead()}
                  >
                    Mark all read
                  </button>
                )}
              </div>
              <DropdownMenuSeparator />
              {notifications.length === 0 ? (
                <p className="px-3 py-6 text-center text-sm text-muted-foreground">
                  No approval notifications
                </p>
              ) : (
                notifications.map((n) => (
                  <DropdownMenuItem
                    key={n.id}
                    className={`flex cursor-pointer flex-col items-start gap-0.5 px-3 py-2.5 ${
                      n.isRead ? "" : "bg-primary/5"
                    }`}
                    onClick={() => void openNotification(n)}
                  >
                    <span className="line-clamp-1 text-sm font-medium text-foreground">{n.title}</span>
                    <span className="line-clamp-2 text-xs text-muted-foreground">{n.message}</span>
                    {n.createdAt && (
                      <span className="mt-0.5 text-[10px] text-muted-foreground">
                        {new Date(n.createdAt).toLocaleString()}
                      </span>
                    )}
                  </DropdownMenuItem>
                ))
              )}
            </DropdownMenuContent>
          </DropdownMenu>
          <button
            type="button"
            className="hidden rounded-lg p-2 text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-700 xl:inline-flex"
            aria-label="Help"
          >
            <HelpCircle className="h-6 w-6" />
          </button>
        </div>

        <div className="mx-0.5 h-6 w-px shrink-0 bg-gray-200 sm:mx-1.5 sm:h-8 xl:mx-2" aria-hidden />

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="flex shrink-0 items-center gap-2 rounded-lg py-1 pl-0.5 text-left transition-colors hover:bg-gray-50 sm:pl-1 xl:gap-3 xl:pl-2 xl:py-1.5"
            >
              <div className="hidden min-w-0 flex-col items-start xl:flex">
                <span className="max-w-[12rem] truncate text-sm font-semibold text-[#101727]">
                  {displayName}
                </span>
                <span className="max-w-[14rem] truncate text-xs text-[#697282]" title={roleLine}>
                  {roleLine}
                </span>
              </div>
              <Avatar className="h-8 w-8 shrink-0 rounded-full border-2 border-gray-100 sm:h-9 sm:w-9 xl:h-10 xl:w-10">
                <AvatarImage
                  src="https://randomuser.me/api/portraits/women/44.jpg"
                  alt={displayName}
                />
                <AvatarFallback className="bg-gray-200 text-sm text-[#6B7280]">
                  {initials || <User className="h-5 w-5" />}
                </AvatarFallback>
              </Avatar>
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <div className="px-2 py-1.5 xl:hidden">
              <p className="truncate text-sm font-semibold text-[#101727]">{displayName}</p>
              <p className="truncate text-xs text-[#697282]">{roleLine}</p>
            </div>
            <DropdownMenuSeparator className="xl:hidden" />
            <DropdownMenuItem
              onClick={handleLogout}
              className="cursor-pointer text-destructive focus:text-destructive"
            >
              <LogOut className="mr-2 h-4 w-4" />
              Log out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  )
})
