import { useMemo } from 'react'
import { useLocale, useTranslation } from '@/i18n'

/** Locale-aware formatters. Every market date and time is read in Asia/Taipei. */
export const MARKET_TIME_ZONE = 'Asia/Taipei'

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

export function formatNumber(locale: string, value: number, fractionDigits = 0): string {
  return numberFormat(locale, {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(value)
}

export function formatPrice(locale: string, value: number): string {
  return formatNumber(locale, value, value >= 1000 ? 0 : 2)
}

/** Signed value, so a change never relies on color alone: +1.25 / −0.80 / 0.00. */
export function formatSigned(locale: string, value: number, fractionDigits = 2): string {
  return numberFormat(locale, {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
    signDisplay: 'exceptZero',
  }).format(value)
}

export function formatSignedPercent(locale: string, ratio: number, fractionDigits = 2): string {
  return numberFormat(locale, {
    style: 'percent',
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
    signDisplay: 'exceptZero',
  }).format(ratio)
}

/** A board lot on TWSE and TPEx is 1,000 shares; Taiwan investors read a stock's volume in lots (張). */
export const SHARES_PER_LOT = 1000

export function formatCompact(locale: string, value: number): string {
  return numberFormat(locale, { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

/** Whole lots under ten thousand keep their digits and grouping; larger counts shorten to 萬 or K. */
function formatLotCount(locale: string, lots: number): string {
  return lots < 10_000 ? formatNumber(locale, Math.round(lots)) : formatCompact(locale, lots)
}

export function formatDate(locale: string, isoDate: string, style: 'short' | 'long' = 'short'): string {
  const options: Intl.DateTimeFormatOptions =
    style === 'long'
      ? { year: 'numeric', month: 'long', day: 'numeric', weekday: 'short' }
      : { year: 'numeric', month: '2-digit', day: '2-digit' }
  return dateFormat(locale, options).format(toMarketDate(isoDate))
}

export function formatMonthDay(locale: string, isoDate: string): string {
  return dateFormat(locale, { month: 'numeric', day: 'numeric' }).format(toMarketDate(isoDate))
}

export function formatDateTime(locale: string, isoDateTime: string): string {
  return dateFormat(locale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(isoDateTime))
}

/** A moment's day and time in Taipei, short: 11/4 13:30. */
export function formatMonthDayTime(locale: string, isoDateTime: string): string {
  return dateFormat(locale, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(isoDateTime))
}

/** A bare trading date (YYYY-MM-DD) is noon in Taipei, so no time zone shifts it to another day. */
function toMarketDate(iso: string): Date {
  return iso.length === 10 ? new Date(`${iso}T12:00:00+08:00`) : new Date(iso)
}

/** The formatters bound to the reader's locale. */
export function useFormat() {
  const locale = useLocale()
  const { t } = useTranslation()
  return useMemo(
    () => ({
      number: (value: number, fractionDigits?: number) => formatNumber(locale, value, fractionDigits),
      price: (value: number) => formatPrice(locale, value),
      compact: (value: number) => formatCompact(locale, value),
      /** A stock's volume in shares, read in lots: "8,234張", "3.7萬張", "37K lots". */
      lots: (shares: number) => t('units.lots', { value: formatLotCount(locale, shares / SHARES_PER_LOT) }),
      date: (isoDate: string, style?: 'short' | 'long') => formatDate(locale, isoDate, style),
      monthDay: (isoDate: string) => formatMonthDay(locale, isoDate),
      /** The session a price closed, said where it is not the latest: "11/2 收盤". */
      closeOn: (isoDate: string) => t('units.closeOn', { date: formatMonthDay(locale, isoDate) }),
    }),
    [locale, t],
  )
}
