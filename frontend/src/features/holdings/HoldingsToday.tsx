import { Briefcase, CalendarClock } from 'lucide-react'
import { Link } from 'react-router'
import { useTranslation } from '@/i18n'
import { isApiError } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { Button } from '@/shared/ui/button'
import { ErrorState } from '@/shared/ui/error-state'
import { Panel, PanelLink } from '@/shared/ui/panel'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { Skeleton } from '@/shared/ui/skeleton'
import { StateBlock } from '@/shared/ui/state-block'
import { useHoldings } from './api'
import { PortfolioFigures } from './HoldingsPage'

/** The portfolio's figures for the home page, the same ones My holdings leads with, and the way to the page. */
export function HoldingsToday({ className }: { className?: string }) {
  const { t } = useTranslation('holdings')
  const holdings = useHoldings(null)
  const enter = (
    <Button asChild variant="outline">
      <Link to={paths.holdings}>{t('today.enter')}</Link>
    </Button>
  )
  return (
    <Panel className={className} title={t('title')} description={t('summary.question')} aside={<PanelLink to={paths.holdings}>{t('today.all')}</PanelLink>}>
      <RequireSignIn reason={t('signIn')}>
        {holdings.isPending ? (
          <Skeleton className="h-32 rounded-lg" />
        ) : holdings.isError ? (
          isApiError(holdings.error) && holdings.error.code === 'ranking_unavailable' ? (
            <StateBlock icon={CalendarClock} title={t('noDecision.title')} description={t('noDecision.description')} />
          ) : (
            <ErrorState error={holdings.error} title={t('loadFailed')} onRetry={() => void holdings.refetch()} />
          )
        ) : holdings.data.holdings.length === 0 ? (
          <StateBlock icon={Briefcase} title={t('empty.title')} description={t('today.empty')} action={enter} />
        ) : (
          <PortfolioFigures holdings={holdings.data} />
        )}
      </RequireSignIn>
    </Panel>
  )
}
