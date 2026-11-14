import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'
import { useTranslation } from '@/i18n'
import { isApiError } from '@/shared/api'
import { sessionDate } from '@/shared/lib/chart-range'
import { ErrorState } from '@/shared/ui/error-state'
import { PageHeader } from '@/shared/ui/page-header'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { PageSkeleton } from '@/shared/ui/skeleton'
import { useLatestRanking, useRankingBacktest } from './api'
import { Caveats } from './Caveats'
import { LatestRanking, type PreviousRanking } from './LatestRanking'
import { MockAccountFollow } from './MockAccountFollow'
import { choiceOf, choiceParams, decisionDay, periodBefore, periodOf, rankingBefore, type PeriodChoice } from './model'
import { PastMonths } from './PastMonths'
import { NoHistory, RankingRecord, Waiting } from './RankingRecord'

interface RankingPageProps {
  /** Whether the site shows the viewer the mock account, which the ranking can be followed into. */
  mockAccount: boolean
}

/** Which stocks the ranking picks now, the ranking in the viewer's mock account, and what a backtest says following it would have done. */
export function RankingPage({ mockAccount }: RankingPageProps) {
  const { t } = useTranslation('ranking')
  return (
    <div className="page-stack">
      <PageHeader title={t('page.title')} description={t('page.description')} />
      <RequireSignIn layout="page" reason={t('signIn')}>
        <Workbench mockAccount={mockAccount} />
      </RequireSignIn>
    </div>
  )
}

/**
 * The month's stocks lead, because they are what the reader came for. From 1280 px the mock account's follow and the
 * backtest sit beside them; narrower, they follow them. The caveats and the backtest's past months run across.
 * The period and the month open are the address's, so both survive a reload. The replays are asked only once the
 * latest ranking has answered: the server reads its whole history for the first answer, and one read serves the rest.
 */
function Workbench({ mockAccount }: RankingPageProps) {
  const { t } = useTranslation('ranking')
  const [params, setParams] = useSearchParams()
  const [today] = useState(() => sessionDate(new Date().toISOString()))
  const choice = useMemo(() => choiceOf(params), [params])
  const latest = useLatestRanking()
  const decidedOn = latest.data?.decided_on ?? null
  const record = useRankingBacktest(decidedOn ? periodOf(choice, today) : null, { keepShown: true })
  const before = useRankingBacktest(decidedOn ? periodBefore(decidedOn) : null)
  const choose = (next: PeriodChoice) => setParams(choiceParams(next))

  if (latest.isPending) {
    return (
      <div className="card-stack">
        <Waiting />
        <div className="card-grid xl:grid-cols-2">
          <PageSkeleton />
          <PageSkeleton />
        </div>
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
  const shown = record.data && !record.isPlaceholderData ? record.data : null

  return (
    <div className="card-grid xl:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <LatestRanking className={mockAccount ? 'xl:row-span-2' : undefined} ranking={ranking} previous={previous} decisionDay={decisionDay(decisions)!} today={today} />
      {mockAccount && <MockAccountFollow ranking={ranking} />}
      <RankingRecord choice={choice} today={today} onChoose={choose} query={record} />
      <Caveats className="xl:col-span-2" />
      {shown && <PastMonths className="xl:col-span-2" backtest={shown} />}
    </div>
  )
}
