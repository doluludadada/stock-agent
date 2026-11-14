import { useCallback, useState } from 'react'
import type { SectionKey } from '../pages'

export const OPENED_SECTIONS_STORAGE_KEY = 'stock-agent.nav.opened'

function readOpened(): SectionKey[] {
  try {
    const saved: unknown = JSON.parse(window.localStorage.getItem(OPENED_SECTIONS_STORAGE_KEY) ?? '[]')
    return Array.isArray(saved) ? (saved.filter((key) => typeof key === 'string') as SectionKey[]) : []
  } catch {
    return []
  }
}

/** The folded navigation sections this reader opened, remembered per browser. Without storage they last the visit. */
export function useOpenedSections(): { opened: readonly SectionKey[]; toggle: (key: SectionKey) => void } {
  const [opened, setOpened] = useState<readonly SectionKey[]>(readOpened)

  const toggle = useCallback(
    (key: SectionKey) => {
      const next = opened.includes(key) ? opened.filter((item) => item !== key) : [...opened, key]
      setOpened(next)
      try {
        window.localStorage.setItem(OPENED_SECTIONS_STORAGE_KEY, JSON.stringify(next))
      } catch {
        // The section still opens for this visit when storage is unavailable.
      }
    },
    [opened],
  )

  return { opened, toggle }
}
