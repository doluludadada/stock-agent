/** The API's bounds (openapi.json): a target P/E above 0 and at most 1000, a minimum undervaluation from 0 to 10. */
export const TARGET_PE_MAX = 1000
export const MIN_UNDERVALUATION_MAX = 10

/** Form starting values, not settings: a common long-run multiple and a margin worth a look. */
export const DEFAULT_TARGET_PE = '15'
export const DEFAULT_MIN_UNDERVALUATION_PERCENT = '30'

/** A typed target P/E, or null when the text is not one the API takes. */
export function parseTargetPe(text: string): number | null {
  const value = Number(text)
  return text.trim() !== '' && value > 0 && value <= TARGET_PE_MAX ? value : null
}

/** A typed percentage as the API's ratio (30 → 0.3), or null when out of bounds. */
export function parseMinUndervaluation(percent: string): number | null {
  const ratio = Number(percent) / 100
  return percent.trim() !== '' && ratio >= 0 && ratio <= MIN_UNDERVALUATION_MAX ? ratio : null
}
