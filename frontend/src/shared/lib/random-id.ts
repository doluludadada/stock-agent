const HEX_DIGITS_PER_BYTE = 2

/**
 * A random id of `digits` lowercase hex digits. It reads `crypto.getRandomValues`, which every page has. The browser
 * gives `crypto.randomUUID` only to a secure context, and the site also runs over plain http at a host name
 * (frontend/docs/deployment.md), where a call to it throws.
 */
export function randomHex(digits: number): string {
  const bytes = crypto.getRandomValues(new Uint8Array(Math.ceil(digits / HEX_DIGITS_PER_BYTE)))
  return Array.from(bytes, (byte) => byte.toString(16).padStart(HEX_DIGITS_PER_BYTE, '0')).join('').slice(0, digits)
}
