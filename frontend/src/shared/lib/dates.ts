/** Calendar days as the API takes them (YYYY-MM-DD), the spans built from them and what is wrong with a typed one. */

/** A span of calendar days, both ends included. */
export interface Period {
  first: string
  last: string
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/

export function isIsoDate(text: string | null): text is string {
  return text !== null && ISO_DATE.test(text) && !Number.isNaN(new Date(`${text}T00:00:00Z`).getTime())
}

/** The same day `months` earlier, or that month's last day when it is shorter. */
export function monthsBefore(date: string, months: number): string {
  const [year, month, day] = date.split('-').map(Number) as [number, number, number]
  const target = new Date(Date.UTC(year, month - 1 - months, 1))
  const lastDay = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0)).getUTCDate()
  target.setUTCDate(Math.min(day, lastDay))
  return target.toISOString().slice(0, 10)
}

export type PeriodProblem = 'dateRequired' | 'beforeFirst' | 'afterLast' | 'firstAfterLast'

function dayProblem(date: string, bounds: Partial<Period>): PeriodProblem | null {
  if (!isIsoDate(date)) return 'dateRequired'
  if (bounds.first !== undefined && date < bounds.first) return 'beforeFirst'
  if (bounds.last !== undefined && date > bounds.last) return 'afterLast'
  return null
}

/** What is wrong with two typed days, at the field that is wrong; empty when they are a period within the bounds. */
export function periodProblems(draft: Period, bounds: Partial<Period>): Partial<Record<keyof Period, PeriodProblem>> {
  const first = dayProblem(draft.first, bounds)
  const last = dayProblem(draft.last, bounds) ?? (!first && draft.first > draft.last ? 'firstAfterLast' : null)
  return { ...(first && { first }), ...(last && { last }) }
}
