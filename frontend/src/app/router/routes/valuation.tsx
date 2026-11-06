import { ValuationPage } from '@/features/valuation'
import { useTranslation } from '@/i18n'
import { RequireCapability } from '../RouteFallbacks'

export function ValuationRoute() {
  const { t } = useTranslation('valuation')
  return (
    <RequireCapability capability="mops" title={t('notOffered.title')} reason={t('notOffered.reason')}>
      <ValuationPage />
    </RequireCapability>
  )
}
