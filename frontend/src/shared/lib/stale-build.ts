const RELOADED_AT = 'stale-build-reloaded-at'
const AGAIN_AFTER_MS = 60_000

/**
 * A tab opened before a deploy still asks for the old build's code, which the server no longer has. Vite reports each
 * such failed import as `vite:preloadError`; the page then loads once more, which fetches the new build. Another
 * failure within a minute shows the route's error page instead, so a missing file never reloads in a loop, and nor
 * does a tab whose sessionStorage refuses the note. Offline, the import failed for want of a network, and a reload
 * would only replace the page with the browser's own error.
 */
export function reloadOnStaleBuild(target: Window = window, now: () => number = Date.now) {
  target.addEventListener('vite:preloadError', (event) => {
    if (!target.navigator.onLine) return
    try {
      if (now() - Number(target.sessionStorage.getItem(RELOADED_AT) ?? 0) < AGAIN_AFTER_MS) return
      target.sessionStorage.setItem(RELOADED_AT, String(now()))
    } catch {
      return
    }
    event.preventDefault()
    target.location.reload()
  })
}
