import { ListX } from 'lucide-react'
import { useTranslation } from '@/i18n'
import { isApiError } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { useFormat } from '@/shared/lib/format'
import { ErrorState } from '@/shared/ui/error-state'
import { NotAdviceNote } from '@/shared/ui/not-advice-note'
import { Panel, PanelLink } from '@/shared/ui/panel'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { StateBlock } from '@/shared/ui/state-block'
import { useLatestRanking } from './api'
import { BackfillCommand } from './LatestRanking'
import { RankedStocksTable } from './RankedStocksTable'
import { NoHistory, Waiting } from './RankingRecord'

/** How many of the ranking's stocks the home page lists beside the other cards, and in one column; the ranking page lists them all. */
const SHOWN = { wide: 10, narrow: 5 }

/** The ranking for the home page: the latest decision and its first stocks, with the way to the whole page. */
export function RankingToday({ className }: { className?: string }) {
  const { t } = useTranslation('ranking')
  const format = useFormat()
  const latest = useLatestRanking()
  const ranking = latest.data
  const [year, month] = (ranking?.revenue_month ?? '').split('-').map(Number) as [number, number]
  return (
    <Panel
      flush
      className={className}
      title={t('latest.title')}
      description={ranking ? t('today.decided', { date: format.date(ranking.decided_on), month: format.yearMonth(year, month) }) : t('today.lead')}
      aside={<PanelLink to={paths.ranking}>{t('today.all')}</PanelLink>}
      footer={ranking && ranking.stocks.length > 0 && <NotAdviceNote className="px-2.5 py-1.5" />}
    >
      <RequireSignIn reason={t('signIn')}>
        {latest.isPending ? (
          <div className="p-4 md:p-5">
            <Waiting />
          </div>
        ) : latest.isError ? (
          isApiError(latest.error) && latest.error.code === 'ranking_unavailable' ? (
            <NoHistory />
          ) : (
            <ErrorState error={latest.error} title={t('latest.loadFailed')} onRetry={() => void latest.refetch()} />
          )
        ) : latest.data.stocks.length === 0 ? (
          <StateBlock icon={ListX} title={t('latest.none.title')} description={t('latest.none.description', { month: format.yearMonth(year, month) })} action={<BackfillCommand />} />
        ) : (
          <RankedStocksTable label={t('latest.title')} rows={latest.data.stocks.slice(0, SHOWN.wide).map((stock, index) => ({ stock, className: index < SHOWN.narrow ? undefined : 'max-xl:hidden' }))} />
        )}
      </RequireSignIn>
    </Panel>
  )
}
