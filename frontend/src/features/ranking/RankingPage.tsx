import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'
import { useTranslation } from '@/i18n'
import { isApiError } from '@/shared/api'
import { sessionDate } from '@/shared/lib/chart-range'
import { ErrorState } from '@/shared/ui/error-state'
import { PageHeader } from '@/shared/ui/page-header'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { PageSkeleton } from '@/shared/ui/skeleton'
import { useLatestRanking, useRankingBacktest, useRankingFormulas } from './api'
import { FormulaComparison } from './FormulaComparison'
import { LatestRanking, type PreviousRanking } from './LatestRanking'
import { MockAccountFollow } from './MockAccountFollow'
import { choiceOf, choiceParams, decisionDay, nextDecision, periodBefore, periodOf, rankingBefore, weekdayAfter } from './model'
import { NoHistory, RankingRecord, Waiting } from './RankingRecord'

interface RankingPageProps {
  /** Whether the site shows the viewer the mock account, which the ranking can be followed into. */
  mockAccount: boolean
}

export function RankingPage({ mockAccount }: RankingPageProps) {
  const { t } = useTranslation('ranking')
  return (
    <div className="page-stack">
      <PageHeader title={t('page.title')} />
      <RequireSignIn layout="page" reason={t('signIn')}>
        <Workbench mockAccount={mockAccount} />
      </RequireSignIn>
    </div>
  )
}

/** The address parameters that live in the backtest's detail, so an address that names one opens it. */
const DETAIL_PARAMS = ['period', 'first', 'last', 'month']

/**
 * The month's stocks lead. The mock account's follow, the backtest's figures and the formulas compared come after
 * them, beside them from 1280 px. The replays are asked only once the latest ranking has answered: the server reads
 * its whole history for the first answer, and one read serves the rest. The comparison waits for the backtest.
 */
function Workbench({ mockAccount }: RankingPageProps) {
  const { t } = useTranslation('ranking')
  const [params, setParams] = useSearchParams()
  const [today] = useState(() => sessionDate(new Date().toISOString()))
  const [detailAtFirst] = useState(() => DETAIL_PARAMS.some((name) => params.has(name)))
  const choice = useMemo(() => choiceOf(params), [params])
  const latest = useLatestRanking()
  const decidedOn = latest.data?.decided_on ?? null
  const period = decidedOn ? periodOf(choice, today) : null
  const record = useRankingBacktest(period, { keepShown: true })
  const before = useRankingBacktest(decidedOn ? periodBefore(decidedOn) : null)
  const formulas = useRankingFormulas(record.data && !record.isPlaceholderData ? period : null)

  if (latest.isPending) {
    return (
      <div className="card-stack">
        <Waiting />
        <PageSkeleton />
      </div>
    )
  }
  if (latest.isError) {
    return isApiError(latest.error) && latest.error.code === 'ranking_unavailable' ? (
      <NoHistory className="rounded-2xl border bg-card py-12" />
    ) : (
      <ErrorState error={latest.error} title={t('latest.loadFailed')} onRetry={() => void latest.refetch()} framed />
    )
  }

  const ranking = latest.data
  const previous: PreviousRanking = before.data ? { status: 'ready', ranking: rankingBefore(before.data.rankings, ranking.decided_on) } : before.isError ? { status: 'failed' } : { status: 'loading' }
  const decisions = [ranking.decided_on, ...(record.data?.rankings ?? []).map((item) => item.decided_on), ...(before.data?.rankings ?? []).map((item) => item.decided_on)]

  return (
    <div className="card-grid xl:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <LatestRanking ranking={ranking} previous={previous} decisionDay={decisionDay(decisions)!} today={today} />
      <div className="card-stack">
        {mockAccount && <MockAccountFollow ranking={ranking} nextFollow={weekdayAfter(nextDecision(ranking.decided_on, decisionDay(decisions)!, today).on)} />}
        <RankingRecord choice={choice} today={today} onChoose={(next) => setParams(choiceParams(next))} query={record} detailAtFirst={detailAtFirst} />
        {record.data && <FormulaComparison query={formulas} />}
      </div>
    </div>
  )
}
