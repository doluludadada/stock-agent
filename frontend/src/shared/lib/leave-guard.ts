import { useCallback, useEffect, useRef } from 'react'
import { useBlocker } from 'react-router'

type Leaving = 'route' | 'document'

/**
 * Asks before an unsaved page is left; `query: 'leaves'` counts a change of the query alone, for a page whose query names
 * the draft (the designer's `?builtin=`), unlike one whose query is its own state (the settings page's `?google=`).
 * `release` lets the page go without asking until `unsaved` changes, for a navigation it starts before it renders again:
 * `'route'` to another page of the app, `'document'` out of the app (the settings page's trip to Google), which leaves the
 * in-app question on for a page that comes back from the bfcache or never left.
 */
export function useLeaveGuard(unsaved: boolean, query: 'leaves' | 'stays') {
  const asks = useRef<Record<Leaving, boolean>>({ route: unsaved, document: unsaved })
  useEffect(() => {
    asks.current = { route: unsaved, document: unsaved }
    if (!unsaved) return
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (asks.current.document) event.preventDefault()
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [unsaved])
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      asks.current.route && (currentLocation.pathname !== nextLocation.pathname || (query === 'leaves' && currentLocation.search !== nextLocation.search)),
  )
  const release = useCallback((leaving: Leaving) => {
    asks.current = { ...asks.current, [leaving]: false }
  }, [])
  return { blocker, release }
}
