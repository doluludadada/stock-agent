import { useTranslation } from '@/i18n'
import { useFormat } from '@/shared/lib/format'
import { cn } from '@/shared/lib/utils'

interface QuoteTimeProps {
  /** When today's quote last traded; null for a settled close, which says its `session` instead. */
  tradedAt: string | null
  /** The session a settled close is of, YYYY-MM-DD in Taipei. A caller that only ever shows a quote gives none. */
  session?: string
  /** A session trades, so the quote still changes. */
  live: boolean
  className?: string
}

/**
 * When a shown price is from: a settled close says its session; today's quote says its last trade's time, with the
 * live mark while the session trades. The mark is the brand's dot and a word, never a market color.
 */
export function QuoteTime({ tradedAt, session, live, className }: QuoteTimeProps) {
  const { t } = useTranslation()
  const format = useFormat()
  if (!tradedAt) return session ? <span className={className}>{format.closeOn(session)}</span> : null
  return (
    <span className={cn('inline-flex items-center gap-1 whitespace-nowrap', className)} data-testid="quote-time">
      {live && <span aria-hidden className="size-1.5 rounded-full bg-brand" />}
      {t(live ? 'quote.live' : 'quote.lastTrade', { time: format.time(tradedAt) })}
    </span>
  )
}
