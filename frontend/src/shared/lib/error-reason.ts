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
  realtime_quotes_unavailable: 'refusal.realtime_quotes_unavailable',
  mops_unavailable: 'refusal.mops_unavailable',
  broker_unavailable: 'refusal.broker_unavailable',
  real_broker_refused: 'refusal.real_broker_refused',
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
