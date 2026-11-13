import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'
import { useTranslation } from '@/i18n'
import { isApiError } from '@/shared/api'
import { sessionDate } from '@/shared/lib/chart-range'
import { ErrorState } from '@/shared/ui/error-state'
import { PageHeader } from '@/shared/ui/page-header'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { Skeleton } from '@/shared/ui/skeleton'
import { useLatestRanking, useRankingBacktest } from './api'
import { Caveats } from './Caveats'
import { LatestRanking, type PreviousRanking } from './LatestRanking'
import { choiceOf, choiceParams, decisionDay, periodBefore, periodOf, rankingBefore, type PeriodChoice } from './model'
import { PastMonths } from './PastMonths'
import { NoHistory, RankingRecord, Waiting } from './RankingRecord'

/** Which stocks the monthly ranking picks now, and whether following it would have beaten the benchmark. */
export function RankingPage() {
  const { t } = useTranslation('ranking')
  return (
    <div className="space-y-5 lg:space-y-6">
      <PageHeader eyebrow={t('common:nav.section.research')} title={t('page.title')} description={t('page.description')} />
      <RequireSignIn layout="page" reason={t('signIn')}>
        <Workbench />
      </RequireSignIn>
    </div>
  )
}

/**
 * The latest ranking beside its record from 1280 px, above it when narrower; the caveats and the past months across.
 * The period and the month open are the address's, so both survive a reload. The replays are asked only once the
 * latest ranking has answered: the server reads its whole history for the first answer, and one read serves the rest.
 */
function Workbench() {
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
      <div className="space-y-4 lg:space-y-5">
        <Waiting />
        <div className="grid gap-4 lg:gap-5 xl:grid-cols-2">
          <Skeleton className="h-96 rounded-2xl" />
          <Skeleton className="h-96 rounded-2xl" />
        </div>
      </div>
    )
  }
  if (latest.isError) {
    return isApiError(latest.error) && latest.error.code === 'ranking_unavailable' ? (
      <NoHistory className="rounded-2xl border bg-card py-12" />
    ) : (
      <ErrorState error={latest.error} title={t('latest.loadFailed')} onRetry={() => void latest.refetch()} className="rounded-2xl border bg-card py-12" />
    )
  }

  const ranking = latest.data
  const previous: PreviousRanking = before.data ? { status: 'ready', ranking: rankingBefore(before.data.rankings, ranking.decided_on) } : before.isError ? { status: 'failed' } : { status: 'loading' }
  const decisions = [ranking.decided_on, ...(record.data?.rankings ?? []).map((item) => item.decided_on), ...(before.data?.rankings ?? []).map((item) => item.decided_on)]
  const shown = record.data && !record.isPlaceholderData ? record.data : null

  return (
    <div className="grid items-start gap-4 lg:gap-5 xl:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <LatestRanking ranking={ranking} previous={previous} decisionDay={decisionDay(decisions)!} today={today} />
      <RankingRecord choice={choice} today={today} onChoose={choose} query={record} />
      <Caveats className="xl:col-span-2" />
      {shown && <PastMonths className="xl:col-span-2" backtest={shown} />}
    </div>
  )
}
