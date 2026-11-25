import { useCallback } from 'react'
import { useTranslation } from '@/i18n'
import { isApiError, type ErrorCode } from '@/shared/api'

/** The refusals said the same on every page, by the server's code. A page with its own words for a code says them first. */
const BY_CODE = {
  too_many_runs: 'refusal.too_many_runs',
  too_many_backtests: 'refusal.too_many_backtests',
  ai_allowance_spent: 'refusal.ai_allowance_spent',
  brief_limit_reached: 'refusal.brief_limit_reached',
  run_in_progress: 'refusal.run_in_progress',
  listing_unavailable: 'refusal.listing_unavailable',
  broker_not_answering: 'refusal.broker_not_answering',
  ranking_unavailable: 'refusal.ranking_unavailable',
  realtime_quotes_unavailable: 'refusal.realtime_quotes_unavailable',
  mops_unavailable: 'refusal.mops_unavailable',
  broker_unavailable: 'refusal.broker_unavailable',
  real_broker_refused: 'refusal.real_broker_refused',
  not_simulation: 'refusal.not_simulation',
  follow_broker_not_offered: 'refusal.follow_broker_not_offered',
  ordering_off: 'refusal.ordering_off',
  follow_account_changed: 'refusal.follow_account_changed',
  administrators_only: 'refusal.administrators_only',
  feature_hidden: 'refusal.feature_hidden',
} as const satisfies Partial<Record<ErrorCode, string>>

const hasWords = (code: ErrorCode): code is keyof typeof BY_CODE => Object.hasOwn(BY_CODE, code)

/**
 * Why a request failed, in the reader's language: by the refusal's code where the app has words for it, else by the
 * kind of failure. The server's own sentence is English, so it is never shown.
 */
export function useErrorReason(): (error: unknown) => string {
  const { t } = useTranslation()
  return useCallback(
    (error: unknown) => {
      if (!isApiError(error)) return t('errors.server')
      return error.code && hasWords(error.code) ? t(BY_CODE[error.code]) : t(`errors.${error.kind}`)
    },
    [t],
  )
}

/** A follow's own words for the refusals a run's follow and the ranking's share; the ranking words `nothing_to_follow` per account. */
const FOLLOW_REFUSALS = {
  outside_follow_window: 'runs:follow.refused.window',
  realtime_quotes_unavailable: 'runs:follow.refused.quotes',
  run_in_progress: 'runs:busy',
} as const satisfies Partial<Record<ErrorCode, string>>

const hasFollowWords = (code: ErrorCode): code is keyof typeof FOLLOW_REFUSALS => Object.hasOwn(FOLLOW_REFUSALS, code)

/** Why a follow did not start, in the reader's language; `upToDate` is what the page says when nothing is left to follow. */
export function useFollowRefusal(): (error: unknown, upToDate: string) => string {
  const { t } = useTranslation()
  const reason = useErrorReason()
  return useCallback(
    (error: unknown, upToDate: string) => {
      const code = isApiError(error) ? error.code : null
      if (code === 'nothing_to_follow') return upToDate
      return code && hasFollowWords(code) ? t(FOLLOW_REFUSALS[code]) : t('runs:follow.failed', { reason: reason(error) })
    },
    [t, reason],
  )
}
