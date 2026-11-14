import { useTranslation } from '@/i18n'
import { isApiError } from '@/shared/api'
import { useErrorReason } from '@/shared/lib/error-reason'

/** The words for a run or a BUY the server refused to start; a refusal of the broker says to use the mock account. */
export function useStartRefusal(): (error: Error) => string {
  const { t } = useTranslation('runs')
  const reason = useErrorReason()
  return (error) => {
    switch (isApiError(error) ? error.code : null) {
      case 'run_in_progress':
        return t('busy')
      case 'real_broker_refused':
        return t('brokerRefused')
      case 'broker_unavailable':
        return t('brokerUnavailable')
      default:
        return t('startFailed', { reason: reason(error) })
    }
  }
}
