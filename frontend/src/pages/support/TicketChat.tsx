import { useEffect, useRef, useState, type RefObject } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Download,
  FileText,
  ImageIcon,
  Loader2,
  Paperclip,
  Send,
  Smile,
  X,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { getStoredUser } from "@/lib/auth"
import { resolveMediaUrl } from "@/lib/cameras-api"
import {
  fetchTicketChat,
  sendTicketChat,
  type SupportComment,
  type SupportTicket,
} from "@/lib/support-api"
import { cn } from "@/lib/utils"

const EMOJIS = [
  "😀", "😁", "😂", "😊", "🙂", "😉", "😍", "😘",
  "😢", "😭", "😤", "😡", "🤔", "😅", "👍", "👎",
  "✅", "❌", "🙏", "👏", "🔥", "⭐", "🎉", "💯",
  "📎", "📷", "💻", "🔧", "⚠️", "ℹ️", "🕐", "📌",
]

type RoleStyle = {
  avatar: string
  badge: string
  bubble: string
  label: string
}

function roleStyle(role?: string): RoleStyle {
  const r = (role || "").toUpperCase()
  if (r === "SUPPORT") {
    return {
      label: "Support",
      avatar: "bg-[#059669]",
      badge: "bg-[#D1FAE5] text-[#065F46]",
      bubble: "border border-[#A7F3D0] bg-[#ECFDF5]",
    }
  }
  if (r === "DEVELOPER") {
    return {
      label: "Developer",
      avatar: "bg-[#7C3AED]",
      badge: "bg-[#EDE9FE] text-[#5B21B6]",
      bubble: "border border-[#DDD6FE] bg-[#F5F3FF]",
    }
  }
  if (r === "IT_ADMIN" || r === "IT_SUPERADMIN") {
    return {
      label: "IT Support",
      avatar: "bg-[#D97706]",
      badge: "bg-[#FEF3C7] text-[#92400E]",
      bubble: "border border-[#FDE68A] bg-[#FFFBEB]",
    }
  }
  if (r === "ADMIN" || r === "LOCATION_ADMIN") {
    return {
      label: r === "ADMIN" ? "Super Admin" : "Location Admin",
      avatar: "bg-[#2563EB]",
      badge: "bg-[#DBEAFE] text-[#1E40AF]",
      bubble: "border border-[#BFDBFE] bg-[#EFF6FF]",
    }
  }
  return {
    label: "Requester",
    avatar: "bg-[#3B82F6]",
    badge: "bg-[#DBEAFE] text-[#1E40AF]",
    bubble: "border border-[#BFDBFE] bg-[#EFF6FF]",
  }
}

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase()
  return (name.slice(0, 2) || "?").toUpperCase()
}

function formatMsgTime(iso: string) {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
    })
  } catch {
    return iso
  }
}

function formatBytes(n?: number | null) {
  if (n == null || !Number.isFinite(n)) return ""
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function isImageName(name?: string) {
  return /\.(png|jpe?g|gif|webp|bmp)$/i.test(name || "")
}

function AttachmentBlock({ m }: { m: SupportComment }) {
  const url = m.attachment_url ? resolveMediaUrl(m.attachment_url) : null
  const name = m.attachment_name || "Attachment"
  if (!url && !m.attachment) return null
  const href = url || (m.attachment ? resolveMediaUrl(m.attachment) : "#")

  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="mt-2 flex items-center gap-3 rounded-lg border border-[#BFDBFE] bg-white/80 px-3 py-2 text-sm hover:bg-white"
    >
      <div className="flex h-9 w-9 items-center justify-center rounded-md bg-[#EFF6FF] text-[#2563EB]">
        {isImageName(name) ? <ImageIcon className="h-4 w-4" /> : <FileText className="h-4 w-4" />}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium text-[#111827]">{name}</p>
        {m.attachment_size != null && (
          <p className="text-xs text-[#6B7280]">{formatBytes(m.attachment_size)}</p>
        )}
      </div>
      <Download className="h-4 w-4 shrink-0 text-[#2563EB]" />
    </a>
  )
}

export function TicketChatPanel({
  ticket,
  replyFocusRef,
}: {
  ticket: SupportTicket
  replyFocusRef?: RefObject<HTMLTextAreaElement | null>
}) {
  const qc = useQueryClient()
  const me = getStoredUser()
  const bottomRef = useRef<HTMLDivElement>(null)
  const localRef = useRef<HTMLTextAreaElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const imageRef = useRef<HTMLInputElement>(null)
  const emojiWrapRef = useRef<HTMLDivElement>(null)
  const textareaRef = replyFocusRef || localRef
  const [text, setText] = useState("")
  const [file, setFile] = useState<File | null>(null)
  const [showEmoji, setShowEmoji] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const chatQ = useQuery({
    queryKey: ["support", "chat", ticket.id],
    queryFn: () => fetchTicketChat(ticket.id),
    refetchInterval: 4000,
  })

  const messages = chatQ.data?.messages || ticket.comments || []
  const canChat = Boolean(chatQ.data?.can_chat ?? ticket.can_chat)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages.length])

  useEffect(() => {
    if (!showEmoji) return
    const onDoc = (e: MouseEvent) => {
      if (!emojiWrapRef.current?.contains(e.target as Node)) setShowEmoji(false)
    }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [showEmoji])

  const insertEmoji = (emoji: string) => {
    const el = textareaRef.current
    if (el) {
      const start = el.selectionStart ?? text.length
      const end = el.selectionEnd ?? text.length
      const next = text.slice(0, start) + emoji + text.slice(end)
      setText(next)
      requestAnimationFrame(() => {
        el.focus()
        const pos = start + emoji.length
        el.setSelectionRange(pos, pos)
      })
    } else {
      setText((t) => t + emoji)
    }
  }

  const pickFile = (f: File | null | undefined) => {
    if (!f) return
    if (f.size > 15 * 1024 * 1024) {
      setError("File must be under 15 MB.")
      return
    }
    setError(null)
    setFile(f)
  }

  const sendMut = useMutation({
    mutationFn: () => sendTicketChat(ticket.id, text.trim(), false, file),
    onSuccess: () => {
      setText("")
      setFile(null)
      setShowEmoji(false)
      setError(null)
      if (fileRef.current) fileRef.current.value = ""
      if (imageRef.current) imageRef.current.value = ""
      qc.invalidateQueries({ queryKey: ["support", "chat", ticket.id] })
      qc.invalidateQueries({ queryKey: ["support", "ticket", ticket.id] })
    },
    onError: (e: Error) => setError(e.message),
  })

  const canSend = Boolean(text.trim() || file) && !sendMut.isPending

  return (
    <div className="overflow-hidden rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
      <div className="flex items-center gap-2 border-b border-[#E5E7EB] px-5 py-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#EFF6FF] text-[#2563EB]">
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
        </div>
        <h3 className="text-base font-semibold text-[#111827]">Conversation</h3>
      </div>

      <div className="flex max-h-[480px] min-h-[320px] flex-col">
        <div className="flex-1 space-y-4 overflow-y-auto bg-[#F8FAFC] px-5 py-5">
          {chatQ.isLoading && (
            <p className="text-center text-sm text-[#6B7280]">Loading conversation…</p>
          )}
          {!chatQ.isLoading && messages.length === 0 && (
            <p className="rounded-xl border border-dashed border-[#D1D5DB] bg-white px-4 py-10 text-center text-sm text-[#6B7280]">
              No messages yet. Start the conversation below.
            </p>
          )}
          {messages
            .filter((m) => !m.is_internal)
            .map((m) => {
              const style = roleStyle(m.author_role)
              const mine = me?.id === m.author
              return (
                <div key={m.id} className="flex gap-3">
                  <div
                    className={cn(
                      "flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-sm font-semibold text-white",
                      style.avatar
                    )}
                  >
                    {initials(m.author_name)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="mb-1.5 flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold text-[#111827]">{m.author_name}</span>
                      <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", style.badge)}>
                        {style.label}
                      </span>
                      <span className="text-xs text-[#9CA3AF]">{formatMsgTime(m.created_at)}</span>
                      {mine && <span className="text-[11px] text-[#9CA3AF]">(you)</span>}
                    </div>
                    <div
                      className={cn(
                        "rounded-xl px-4 py-3 text-sm leading-relaxed text-[#1F2937]",
                        style.bubble
                      )}
                    >
                      {m.body && <p className="whitespace-pre-wrap break-words">{m.body}</p>}
                      <AttachmentBlock m={m} />
                    </div>
                  </div>
                </div>
              )
            })}
          <div ref={bottomRef} />
        </div>

        <div className="border-t border-[#E5E7EB] bg-white p-4">
          {error && (
            <p className="mb-2 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>
          )}
          {!canChat ? (
            <p className="rounded-lg bg-[#F3F4F6] px-3 py-3 text-center text-sm text-[#6B7280]">
              Chat is closed — this ticket expired or was cancelled. Previous messages stay visible above.
            </p>
          ) : (
            <>
              {file && (
                <div className="mb-2 flex items-center gap-2 rounded-lg border border-[#BFDBFE] bg-[#EFF6FF] px-3 py-2 text-sm">
                  <Paperclip className="h-4 w-4 text-[#2563EB]" />
                  <span className="min-w-0 flex-1 truncate font-medium text-[#1E40AF]">
                    {file.name}
                  </span>
                  <span className="text-xs text-[#6B7280]">{formatBytes(file.size)}</span>
                  <button
                    type="button"
                    className="rounded p-1 text-[#6B7280] hover:bg-white"
                    onClick={() => {
                      setFile(null)
                      if (fileRef.current) fileRef.current.value = ""
                      if (imageRef.current) imageRef.current.value = ""
                    }}
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              )}
              <Textarea
                ref={textareaRef}
                rows={3}
                placeholder="Type your reply here..."
                className="resize-none border-[#E5E7EB] bg-[#F9FAFB] text-sm focus-visible:ring-[#3B82F6]"
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault()
                    if (canSend) sendMut.mutate()
                  }
                }}
              />
              <div className="mt-3 flex items-center justify-between gap-3">
                <div className="relative flex items-center gap-1 text-[#6B7280]" ref={emojiWrapRef}>
                  <input
                    ref={fileRef}
                    type="file"
                    className="hidden"
                    onChange={(e) => pickFile(e.target.files?.[0])}
                  />
                  <input
                    ref={imageRef}
                    type="file"
                    accept="image/*"
                    className="hidden"
                    onChange={(e) => pickFile(e.target.files?.[0])}
                  />
                  <button
                    type="button"
                    className="rounded-md p-2 hover:bg-[#F3F4F6] hover:text-[#2563EB]"
                    title="Attach file"
                    onClick={() => fileRef.current?.click()}
                  >
                    <Paperclip className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    className="rounded-md p-2 hover:bg-[#F3F4F6] hover:text-[#2563EB]"
                    title="Attach image"
                    onClick={() => imageRef.current?.click()}
                  >
                    <ImageIcon className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    className={cn(
                      "rounded-md p-2 hover:bg-[#F3F4F6] hover:text-[#2563EB]",
                      showEmoji && "bg-[#EFF6FF] text-[#2563EB]"
                    )}
                    title="Emoji"
                    onClick={() => setShowEmoji((v) => !v)}
                  >
                    <Smile className="h-4 w-4" />
                  </button>
                  {showEmoji && (
                    <div className="absolute bottom-10 left-0 z-20 grid w-[280px] grid-cols-8 gap-1 rounded-xl border border-[#E5E7EB] bg-white p-2 shadow-lg">
                      {EMOJIS.map((e) => (
                        <button
                          key={e}
                          type="button"
                          className="rounded-md p-1.5 text-lg hover:bg-[#F3F4F6]"
                          onClick={() => insertEmoji(e)}
                        >
                          {e}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <Button
                  className="bg-[#2563EB] px-5 hover:bg-[#1D4ED8]"
                  disabled={!canSend}
                  onClick={() => sendMut.mutate()}
                >
                  {sendMut.isPending ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Send className="mr-2 h-4 w-4" />
                  )}
                  Send
                </Button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
