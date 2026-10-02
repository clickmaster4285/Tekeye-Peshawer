import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
  type PointerEvent as ReactPointerEvent,
} from "react"
import { useQuery } from "@tanstack/react-query"
import { Link, useLocation } from "react-router-dom"
import { ChevronDown, GripVertical, Loader2, Maximize2, Mic, MicOff, Send, Volume2, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useVoiceAgent, type VoicePhase } from "@/hooks/use-voice-agent"
import { fetchVoiceAgentStatus } from "@/lib/voice-agent-api"
import { cn } from "@/lib/utils"

const PHASE_LABEL: Record<VoicePhase, string> = {
  off: "Voice agent off",
  wake: 'Say "Hello Customs"',
  listening: "Listening…",
  transcribing: "Listening…",
  thinking: "Working on it…",
  speaking: "Speaking…",
  error: "Voice unavailable",
}

const PHASE_ORB: Record<VoicePhase, string> = {
  off: "bg-slate-500 hover:bg-slate-600",
  wake: "bg-slate-800 hover:bg-slate-900",
  listening: "bg-emerald-600 ring-4 ring-emerald-300 animate-pulse",
  transcribing: "bg-emerald-600 ring-4 ring-emerald-300",
  thinking: "bg-amber-500 ring-4 ring-amber-200",
  speaking: "bg-sky-600 ring-4 ring-sky-300",
  error: "bg-red-600 hover:bg-red-700",
}

const POS_KEY = "tekeye.voiceAgent.position"
const ORB = 56

type Pos = { x: number; y: number }

function defaultPos(onAssistantPage: boolean): Pos {
  if (typeof window === "undefined") return { x: 24, y: 24 }
  const margin = 16
  return {
    x: Math.max(margin, window.innerWidth - ORB - margin),
    y: Math.max(margin, window.innerHeight - ORB - margin - (onAssistantPage ? 80 : 0)),
  }
}

function loadPos(onAssistantPage: boolean): Pos {
  try {
    const raw = localStorage.getItem(POS_KEY)
    if (!raw) return defaultPos(onAssistantPage)
    const parsed = JSON.parse(raw) as Pos
    if (typeof parsed?.x === "number" && typeof parsed?.y === "number") {
      return clampPos(parsed)
    }
  } catch {
    /* ignore */
  }
  return defaultPos(onAssistantPage)
}

function clampPos(pos: Pos): Pos {
  if (typeof window === "undefined") return pos
  const margin = 8
  return {
    x: Math.min(Math.max(margin, pos.x), Math.max(margin, window.innerWidth - ORB - margin)),
    y: Math.min(Math.max(margin, pos.y), Math.max(margin, window.innerHeight - ORB - margin)),
  }
}

/** Floating "Hello Customs" voice agent. Rendered only for roles enabled on the backend. */
export function VoiceAgentWidget() {
  const { data: status } = useQuery({
    queryKey: ["voice-agent-status"],
    queryFn: fetchVoiceAgentStatus,
    staleTime: 5 * 60_000,
    retry: 1,
  })
  const agent = useVoiceAgent(status)
  const onAssistantPage = useLocation().pathname === "/assistant"
  const [open, setOpen] = useState(false)
  const [typed, setTyped] = useState("")
  const [pos, setPos] = useState<Pos>(() => loadPos(false))
  const [dragging, setDragging] = useState(false)
  const logRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<{
    pointerId: number
    startX: number
    startY: number
    origX: number
    origY: number
    moved: boolean
  } | null>(null)

  useEffect(() => {
    setPos((p) => clampPos(p))
  }, [onAssistantPage])

  useEffect(() => {
    const onResize = () => setPos((p) => clampPos(p))
    window.addEventListener("resize", onResize)
    return () => window.removeEventListener("resize", onResize)
  }, [])

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight })
  }, [agent.entries, open])

  const persistPos = useCallback((next: Pos) => {
    try {
      localStorage.setItem(POS_KEY, JSON.stringify(next))
    } catch {
      /* ignore */
    }
  }, [])

  const onDragPointerDown = (e: ReactPointerEvent<HTMLElement>) => {
    const target = e.target as HTMLElement
    if (target.closest("a,button:not([data-voice-orb]),input,textarea")) return
    e.currentTarget.setPointerCapture(e.pointerId)
    dragRef.current = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      origX: pos.x,
      origY: pos.y,
      moved: false,
    }
    setDragging(true)
  }

  const onDragPointerMove = (e: ReactPointerEvent<HTMLElement>) => {
    const d = dragRef.current
    if (!d || d.pointerId !== e.pointerId) return
    const dx = e.clientX - d.startX
    const dy = e.clientY - d.startY
    if (Math.abs(dx) + Math.abs(dy) > 4) d.moved = true
    setPos(clampPos({ x: d.origX + dx, y: d.origY + dy }))
  }

  const onDragPointerUp = (e: ReactPointerEvent<HTMLElement>) => {
    const d = dragRef.current
    if (!d || d.pointerId !== e.pointerId) return
    try {
      e.currentTarget.releasePointerCapture(e.pointerId)
    } catch {
      /* ignore */
    }
    const moved = d.moved
    dragRef.current = null
    setDragging(false)
    setPos((p) => {
      const next = clampPos(p)
      persistPos(next)
      return next
    })
    return moved
  }

  if (!status?.enabled) return null

  const busy = agent.phase === "thinking" || agent.phase === "transcribing"
  const onOrbClick = () => {
    if (agent.phase === "off" || agent.phase === "error") void agent.enable()
    else if (agent.phase === "wake") void agent.talkNow()
    else setOpen(true)
  }
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    const text = typed.trim()
    if (!text) return
    setTyped("")
    void agent.talkNow(text)
  }

  // Panel opens away from screen edges; anchored to the orb box (ORB×ORB)
  const panelStyle: CSSProperties = (() => {
    if (typeof window === "undefined") return { bottom: "100%", right: 0, marginBottom: 8 }
    const nearRight = pos.x > window.innerWidth * 0.55
    const nearBottom = pos.y > window.innerHeight * 0.45
    return {
      position: "absolute",
      ...(nearBottom ? { bottom: "100%", marginBottom: 8 } : { top: "100%", marginTop: 8 }),
      ...(nearRight ? { right: 0 } : { left: 0 }),
    }
  })()

  const labelOnLeft = typeof window === "undefined" || pos.x > window.innerWidth * 0.4

  return (
    <div
      className={cn("fixed z-[60]", dragging && "select-none")}
      style={{ left: pos.x, top: pos.y, width: ORB, height: ORB, touchAction: "none" }}
    >
      {open && (
        <div
          className="w-[min(360px,calc(100vw-2rem))] rounded-xl border border-slate-200 bg-white shadow-xl"
          style={panelStyle}
        >
          <div
            className="flex cursor-grab items-center justify-between border-b px-3 py-2 active:cursor-grabbing"
            onPointerDown={onDragPointerDown}
            onPointerMove={onDragPointerMove}
            onPointerUp={onDragPointerUp}
            onPointerCancel={onDragPointerUp}
          >
            <div className="flex min-w-0 items-center gap-2">
              <GripVertical className="h-4 w-4 shrink-0 text-slate-400" aria-hidden />
              <div className="min-w-0">
                <p className="text-sm font-semibold text-slate-900">TekEye Voice Agent</p>
                <p className="text-xs text-slate-500">{PHASE_LABEL[agent.phase]}</p>
              </div>
            </div>
            <div className="flex items-center gap-1">
              <Button size="sm" variant="ghost" asChild title="Open full assistant (chat, reports)">
                <Link to="/assistant" onClick={() => setOpen(false)}>
                  <Maximize2 className="h-4 w-4" />
                </Link>
              </Button>
              {agent.sessionActive && (
                <Button size="sm" variant="ghost" onClick={agent.endSession} title="End conversation">
                  <X className="h-4 w-4" />
                </Button>
              )}
              <Button size="sm" variant="ghost" onClick={() => setOpen(false)} title="Minimise">
                <ChevronDown className="h-4 w-4" />
              </Button>
            </div>
          </div>

          <div ref={logRef} className="max-h-72 space-y-2 overflow-y-auto px-3 py-2 text-sm">
            {agent.entries.length === 0 && (
              <p className="text-xs text-slate-500">
                Turn the microphone on, then say “Hello Customs” and ask in English or Urdu — e.g. “What's happening
                at the main gate?”
              </p>
            )}
            {agent.entries.map((e) =>
              e.role === "system" ? (
                <p key={e.id} className="text-center text-[11px] text-slate-400">
                  {e.text}
                </p>
              ) : (
                <div
                  key={e.id}
                  className={cn(
                    "max-w-[85%] rounded-lg px-3 py-1.5",
                    e.role === "officer" ? "ml-auto bg-slate-900 text-white" : "bg-slate-100 text-slate-900",
                  )}
                >
                  {e.text}
                </div>
              ),
            )}
          </div>

          {agent.phase === "wake" && agent.heard && (
            <p className="px-3 pb-1 text-xs text-slate-500">
              Heard: “{agent.heard}” — start with “Hello Customs”, or tap the mic to talk now.
            </p>
          )}
          {agent.error && <p className="px-3 pb-1 text-xs text-red-600">{agent.error}</p>}

          <form onSubmit={onSubmit} className="flex items-center gap-2 border-t px-3 py-2">
            <Input
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder="Or type a request…"
              className="h-8 text-sm"
              disabled={busy}
            />
            <Button type="submit" size="sm" disabled={busy || !typed.trim()}>
              <Send className="h-4 w-4" />
            </Button>
            {agent.phase !== "off" && (
              <Button type="button" size="sm" variant="outline" onClick={agent.disable} title="Turn microphone off">
                <MicOff className="h-4 w-4" />
              </Button>
            )}
          </form>
        </div>
      )}

      {!open && (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className={cn(
            "absolute top-1/2 z-10 flex max-w-[220px] -translate-y-1/2 items-center gap-2 rounded-full bg-white/95 px-3 py-1 text-xs font-medium shadow",
            labelOnLeft ? "right-full mr-2" : "left-full ml-2",
            agent.error ? "text-red-600" : "text-slate-700",
          )}
          title={agent.error || PHASE_LABEL[agent.phase]}
        >
          {(agent.phase === "wake" || agent.phase === "listening") && (
            <span className="h-1.5 w-10 overflow-hidden rounded-full bg-slate-200" aria-hidden>
              <span
                className="block h-full rounded-full bg-emerald-500 transition-[width] duration-100"
                style={{ width: `${Math.round(agent.level * 100)}%` }}
              />
            </span>
          )}
          <span className="truncate">{agent.error || PHASE_LABEL[agent.phase]}</span>
        </button>
      )}

      <button
        type="button"
        data-voice-orb
        onPointerDown={onDragPointerDown}
        onPointerMove={onDragPointerMove}
        onPointerUp={(e) => {
          const moved = dragRef.current?.moved
          onDragPointerUp(e)
          if (!moved) onOrbClick()
        }}
        onPointerCancel={onDragPointerUp}
        aria-label={PHASE_LABEL[agent.phase]}
        title={
          agent.phase === "wake"
            ? "Drag to move · tap to talk now"
            : `Drag to move · ${PHASE_LABEL[agent.phase]}`
        }
        className={cn(
          "relative z-20 flex h-14 w-14 cursor-grab items-center justify-center rounded-full text-white shadow-lg transition active:cursor-grabbing",
          PHASE_ORB[agent.phase],
        )}
      >
        {busy ? (
          <Loader2 className="h-6 w-6 animate-spin" />
        ) : agent.phase === "speaking" ? (
          <Volume2 className="h-6 w-6" />
        ) : agent.phase === "off" || agent.phase === "error" ? (
          <MicOff className="h-6 w-6" />
        ) : (
          <Mic className="h-6 w-6" />
        )}
      </button>
    </div>
  )
}
