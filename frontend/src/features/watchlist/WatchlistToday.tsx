import { Star } from 'lucide-react'
import { useMemo } from 'react'
import { Link } from 'react-router'
import { useTranslation } from '@/i18n'
import { useStockQuotes } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { Button } from '@/shared/ui/button'
import { ErrorState } from '@/shared/ui/error-state'
import { Panel, PanelLink } from '@/shared/ui/panel'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { Skeleton } from '@/shared/ui/skeleton'
import { StateBlock } from '@/shared/ui/state-block'
import { useWatchlistEntries } from './api'
import { byStock, type WatchRow } from './model'
import { DayPanel } from './WatchlistPage'

/** How the watched stocks did in the latest session, for the home page: the figures the watchlist leads with. */
export function WatchlistToday({ className }: { className?: string }) {
  const { t } = useTranslation('watchlist')
  const entries = useWatchlistEntries()
  const rows = useMemo(() => byStock(entries.data ?? []), [entries.data])
  const open = (
    <Button asChild variant="outline">
      <Link to={paths.watchlist}>{t('action.addStock')}</Link>
    </Button>
  )
  if (rows.length > 0) return <Watched rows={rows} className={className} />
  return (
    <Panel className={className} title={t('title')} aside={<PanelLink to={paths.watchlist}>{t('today.all')}</PanelLink>}>
      <RequireSignIn reason={t('signIn')}>
        {entries.isPending ? (
          <Skeleton className="h-24 rounded-lg" />
        ) : entries.isError ? (
          <ErrorState error={entries.error} title={t('loadFailed')} onRetry={() => void entries.refetch()} />
        ) : (
          <StateBlock icon={Star} title={t('empty.title')} description={t('empty.description')} action={open} />
        )}
      </RequireSignIn>
    </Panel>
  )
}

function Watched({ rows, className }: { rows: WatchRow[]; className?: string }) {
  const { t } = useTranslation('watchlist')
  const codes = useMemo(() => rows.map((row) => row.stockId), [rows])
  const { quotes } = useStockQuotes(codes)
  return <DayPanel rows={rows} quotes={quotes} className={className} title={t('title')} aside={<PanelLink to={paths.watchlist}>{t('today.all')}</PanelLink>} />
}
