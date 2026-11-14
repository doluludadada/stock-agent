import { useEffect } from 'react'

const SITE = 'Stock Agent'

/** Names the browser tab after the page, "<page> · Stock Agent", and gives the site's name back when the page leaves. */
export function usePageTitle(title: string | null | undefined) {
  useEffect(() => {
    if (!title) return
    document.title = `${title} · ${SITE}`
    return () => {
      document.title = SITE
    }
  }, [title])
}
