import { useCallback, useEffect, useRef, useState } from 'react'
import { session } from '@/shared/api'

/** Unsaved work whose page closed because the session ended, by user and page. It lives as long as the tab. */
const kept = new Map<string, unknown>()

const signedInId = () => {
  const current = session.current()
  return current.status === 'signedIn' ? current.user.user_id : null
}

/**
 * Keeps a page's unsaved draft over the end of the session. A 401 or a sign-out replaces the page with the sign-in
 * prompt, which unmounts the draft's state; the draft tracked last is then kept, and `restored` hands it back when the
 * same user opens the page again. Leaving the page while signed in keeps nothing: the page's own leave guard asked.
 */
export function useKeptDraft<T>(name: string): { restored: T | undefined; track: (draft: T | null) => void } {
  const [key] = useState(() => `${signedInId()}:${name}`)
  const [restored] = useState(() => kept.get(key) as T | undefined)
  const latest = useRef<T | null>(restored ?? null)

  useEffect(
    () => () => {
      if (signedInId() === null && latest.current !== null) kept.set(key, latest.current)
      else kept.delete(key)
    },
    [key],
  )

  const track = useCallback((draft: T | null) => {
    latest.current = draft
  }, [])
  return { restored, track }
}
