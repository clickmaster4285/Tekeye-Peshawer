import { useState } from "react"
import { ImageOff } from "lucide-react"
import { resolveMediaUrl } from "@/lib/cameras-api"

/** Small detection picture; opens the full image in a new tab. Placeholder until the city's image arrives. */
export function DetectionThumb({ src, alt, size = 40 }: { src?: string; alt: string; size?: number }) {
  const [failed, setFailed] = useState(false)
  const url = src ? resolveMediaUrl(src) : ""
  const box = { width: size, height: size }

  if (!url || failed) {
    return (
      <span
        className="inline-flex items-center justify-center rounded border border-[#E8F0FA] bg-[#F5F9FE] text-[#A9BBD3]"
        style={box}
        title="Image not received yet"
      >
        <ImageOff className="h-3.5 w-3.5" />
      </span>
    )
  }
  return (
    <a href={url} target="_blank" rel="noreferrer" className="inline-block shrink-0" title="Open image">
      <img
        src={url}
        alt={alt}
        loading="lazy"
        onError={() => setFailed(true)}
        className="rounded border border-[#E8F0FA] object-cover"
        style={box}
      />
    </a>
  )
}
