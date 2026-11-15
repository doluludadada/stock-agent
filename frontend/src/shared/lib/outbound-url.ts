/**
 * A third party's address is a link only when it is plain http or https: anything else (`javascript:`, `data:`, a
 * relative path) gets no link.
 */
export function outboundUrl(url: string | null): string | null {
  if (!url) return null
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? parsed.href : null
  } catch {
    return null
  }
}
