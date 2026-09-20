import { useEffect, useState } from "react"

/**
 * Tracks document visibility so polling loops can pause while the tab is hidden.
 * Camera tiles poll snapshot endpoints that spawn an FFmpeg process per request,
 * so letting them run in a background tab is expensive on the server.
 */
export function usePageVisible(): boolean {
  const [visible, setVisible] = useState(
    () => typeof document === "undefined" || document.visibilityState === "visible"
  )

  useEffect(() => {
    const onChange = () => setVisible(document.visibilityState === "visible")
    document.addEventListener("visibilitychange", onChange)
    return () => document.removeEventListener("visibilitychange", onChange)
  }, [])

  return visible
}
