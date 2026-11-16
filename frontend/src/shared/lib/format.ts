import { useMemo } from 'react'
import { useLocale, useTranslation } from '@/i18n'

/** Every market date and time is read in Asia/Taipei. */
export const MARKET_TIME_ZONE = 'Asia/Taipei'

/** What a figure shows where the server has none. */
export const DASH = '—'

/** A board lot on TWSE and TPEx is 1,000 shares; Taiwan investors read a stock's volume in lots (張). */
const SHARES_PER_LOT = 1000

const cache = new Map<string, Intl.NumberFormat | Intl.DateTimeFormat>()

function numberFormat(locale: string, options: Intl.NumberFormatOptions): Intl.NumberFormat {
  const key = `n|${locale}|${JSON.stringify(options)}`
  let formatter = cache.get(key)
  if (!formatter) {
    formatter = new Intl.NumberFormat(locale, options)
    cache.set(key, formatter)
  }
  return formatter as Intl.NumberFormat
}

function dateFormat(locale: string, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = `d|${locale}|${JSON.stringify(options)}`
  let formatter = cache.get(key)
  if (!formatter) {
    formatter = new Intl.DateTimeFormat(locale, { timeZone: MARKET_TIME_ZONE, ...options })
    cache.set(key, formatter)
  }
  return formatter as Intl.DateTimeFormat
}

/** A time of day as the server writes it, 09:05:00, to the minute; a text that is no time of day stays as it is. */
export function clockTime(time: string): string {
  return time.replace(/^(\d{2}:\d{2}):\d{2}$/, '$1')
}

const digits = (fractionDigits: number): Intl.NumberFormatOptions => ({ minimumFractionDigits: fractionDigits, maximumFractionDigits: fractionDigits })

/** A bare trading date (YYYY-MM-DD) is noon in Taipei, so no time zone shifts it to another day. */
function toMarketDate(iso: string): Date {
  return iso.length === 10 ? new Date(`${iso}T12:00:00+08:00`) : new Date(iso)
}

const DATE_STYLES = {
  short: { year: 'numeric', month: '2-digit', day: '2-digit' },
  long: { year: 'numeric', month: 'long', day: 'numeric', weekday: 'short' },
} as const satisfies Record<string, Intl.DateTimeFormatOptions>

const TIME: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit', hour12: false }

/** The formatters bound to the reader's locale: the one way the app writes a number, a percentage or a date. */
export function useFormat() {
  const locale = useLocale()
  const { t } = useTranslation()
  return useMemo(() => {
    const number = (value: number, fractionDigits = 0) => numberFormat(locale, digits(fractionDigits)).format(value)
    const compact = (value: number) => numberFormat(locale, { notation: 'compact', maximumFractionDigits: 1 }).format(value)
    const monthDay = (isoDate: string) => dateFormat(locale, { month: 'numeric', day: 'numeric' }).format(toMarketDate(isoDate))
    return {
      number,
      price: (value: number) => number(value, value >= 1000 ? 0 : 2),
      /** Signed, so a change never relies on color alone: +1.25, −0.80, 0.00. */
      signed: (value: number, fractionDigits = 2) => numberFormat(locale, { ...digits(fractionDigits), signDisplay: 'exceptZero' }).format(value),
      /** A ratio as a percentage: 0.123 reads 12.3%. */
      percent: (ratio: number, fractionDigits = 1) => numberFormat(locale, { ...digits(fractionDigits), style: 'percent' }).format(ratio),
      signedPercent: (ratio: number, fractionDigits = 2) => numberFormat(locale, { ...digits(fractionDigits), style: 'percent', signDisplay: 'exceptZero' }).format(ratio),
      compact,
      /** A stock's volume in shares, read in lots: "8,234張", "3.7萬張", "37K lots". Under ten thousand lots keep their digits. */
      lots: (shares: number) => {
        const lots = shares / SHARES_PER_LOT
        return t('units.lots', { value: lots < 10_000 ? number(Math.round(lots)) : compact(lots) })
      },
      date: (isoDate: string, style: keyof typeof DATE_STYLES = 'short') => dateFormat(locale, DATE_STYLES[style]).format(toMarketDate(isoDate)),
      monthDay,
      dateTime: (isoDateTime: string) => dateFormat(locale, { ...DATE_STYLES.short, ...TIME }).format(new Date(isoDateTime)),
      /** A moment's day and time in Taipei, short: 11/4 13:30. */
      monthDayTime: (isoDateTime: string) => dateFormat(locale, { month: 'numeric', day: 'numeric', ...TIME }).format(new Date(isoDateTime)),
      /** A moment's time of day in Taipei: 10:32. */
      time: (isoDateTime: string) => dateFormat(locale, TIME).format(new Date(isoDateTime)),
      /** A calendar month: 2026年9月, September 2026. */
      yearMonth: (year: number, month: number) => dateFormat(locale, { year: 'numeric', month: 'long' }).format(new Date(Date.UTC(year, month - 1, 15, 4))),
      /** The session a price closed, said where it is not the latest: "11/2 收盤". */
      closeOn: (isoDate: string) => t('units.closeOn', { date: monthDay(isoDate) }),
    }
  }, [locale, t])
}

export type Format = ReturnType<typeof useFormat>
