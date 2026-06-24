import { useCallback, useEffect, useRef, useState } from "react"
import { apiUrl, authHeaders } from "@/lib/api"

/**
 * Consume a `text/event-stream` POST endpoint. Parses `data: {json}` lines and
 * invokes `onEvent` per event. Aborts on unmount or when a new stream starts.
 */
export function useEventStream<T>() {
  const [running, setRunning] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const stop = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setRunning(false)
  }, [])

  useEffect(() => () => abortRef.current?.abort(), [])

  const start = useCallback(
    async (path: string, body: BodyInit, onEvent: (ev: T) => void): Promise<void> => {
      abortRef.current?.abort()
      const ctrl = new AbortController()
      abortRef.current = ctrl
      setRunning(true)

      try {
        const res = await fetch(apiUrl(path), {
          method: "POST",
          headers: authHeaders(),
          body,
          signal: ctrl.signal,
        })
        if (!res.ok || !res.body) {
          const text = await res.text().catch(() => res.statusText)
          throw new Error(text || res.statusText)
        }

        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let buf = ""
        for (;;) {
          const { done, value } = await reader.read()
          if (done) break
          buf += decoder.decode(value, { stream: true })
          const lines = buf.split("\n")
          buf = lines.pop() ?? ""
          for (const line of lines) {
            if (!line.startsWith("data: ")) continue
            let ev: T
            try {
              ev = JSON.parse(line.slice(6)) as T
            } catch {
              continue // skip malformed frame rather than crash the stream
            }
            onEvent(ev)
          }
        }
      } finally {
        if (abortRef.current === ctrl) abortRef.current = null
        setRunning(false)
      }
    },
    [],
  )

  return { start, stop, running }
}
