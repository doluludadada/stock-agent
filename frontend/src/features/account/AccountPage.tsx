import { FlaskConical, Landmark, Wallet } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { useLocale, useTranslation } from '@/i18n'
import { paths } from '@/shared/config/paths'
import { directionOf } from '@/shared/lib/direction'
import { formatDate, formatDateTime, formatNumber, formatPrice } from '@/shared/lib/format'
import { Badge } from '@/shared/ui/badge'
import { Button } from '@/shared/ui/button'
import { ChangeValue } from '@/shared/ui/change-value'
import { ErrorState } from '@/shared/ui/error-state'
import { Input } from '@/shared/ui/input'
import { PageHeader } from '@/shared/ui/page-header'
import { Panel } from '@/shared/ui/panel'
import { Skeleton } from '@/shared/ui/skeleton'
import { Sparkline } from '@/shared/ui/sparkline'
import { Stat } from '@/shared/ui/stat'
import { StateBlock } from '@/shared/ui/state-block'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/ui/table'
import { RequireUnlock } from '@/shared/ui/unlock'
import { useAccountHistory, type AccountHistory } from './api'

export function AccountPage() {
  const { t } = useTranslation('account')
  return (
    <div className="space-y-4">
      <PageHeader title={t('title')} description={t('description')} />
      <RequireUnlock scope="owner" className="rounded-xl border">
        <Account />
      </RequireUnlock>
    </div>
  )
}

function Account() {
  const { t } = useTranslation('account')
  const locale = useLocale()
  const [asOf, setAsOf] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const history = useAccountHistory(asOf)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setAsOf(/^\d{4}-\d{2}-\d{2}$/.test(draft) ? draft : null)
  }

  if (history.isPending) return <Skeleton className="h-80 rounded-xl" />
  if (history.isError) return <ErrorState error={history.error} title={t('loadFailed')} onRetry={() => void history.refetch()} className="rounded-xl border" />
  const { data } = history

  return (
    <div className="space-y-4">
      <BrokerNotice history={data} />
      <Panel title={t('valueTitle')}>
        <ValueStats value={data.current} />
      </Panel>
      <Positions history={data} />
      <EquityCurve history={data} />
      <Panel
        title={t('asOfLabel')}
        aside={
          <form onSubmit={submit} className="flex items-center gap-2">
            <Input type="date" value={draft} onChange={(event) => setDraft(event.target.value)} aria-label={t('asOfLabel')} className="h-8 w-40" />
            <Button type="submit" variant="outline" size="sm" disabled={history.isFetching}>
              {t('asOfShow')}
            </Button>
          </form>
        }
      >
        {!asOf ? (
          <p className="text-sm text-muted-foreground">{t('asOfHint')}</p>
        ) : data.as_of ? (
          <div className="space-y-3">
            <p className="tabular text-xs text-muted-foreground">{t('asOfTitle', { time: formatDateTime(locale, data.as_of.last_fill_at) })}</p>
            <ValueStats value={data.as_of.value} />
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{t('asOfNone', { date: asOf })}</p>
        )}
      </Panel>
    </div>
  )
}

function BrokerNotice({ history }: { history: AccountHistory }) {
  const { t } = useTranslation('account')
  const mock = history.execution_provider === 'mock'
  const Icon = mock ? FlaskConical : Landmark
  return (
    <p className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground" aria-live="polite">
      <Badge variant="outline" className="gap-1 border-gold/40 font-normal text-gold">
        <Icon aria-hidden className="size-3" />
        {t(`provider.${history.execution_provider}`)} · {t(`orderMode.${history.order_mode}`)}
      </Badge>
      {t(mock ? 'mockNotice' : 'brokerNotice')}
    </p>
  )
}

function ValueStats({ value }: { value: AccountHistory['current'] }) {
  const { t } = useTranslation('account')
  const locale = useLocale()
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
      <Stat label={t('value.equity')}>
        <span className="text-lg font-semibold">{formatNumber(locale, value.equity)}</span>
      </Stat>
      <Stat label={t('value.cash')}>
        <span className="text-lg">{formatNumber(locale, value.cash)}</span>
      </Stat>
      <Stat label={t('value.marketValue')}>
        <span className="text-lg">{formatNumber(locale, value.market_value)}</span>
      </Stat>
      <Stat label={t('value.unrealized')}>
        <ChangeValue value={value.unrealized_pnl} format="absolute" className="text-lg" />
      </Stat>
    </dl>
  )
}

function Positions({ history }: { history: AccountHistory }) {
  const { t } = useTranslation('account')
  const locale = useLocale()
  const positions = history.current.positions
  const live = new Set(history.live_stock_ids)
  return (
    <Panel title={t('positionsTitle')} flush>
      {positions.length === 0 ? (
        <StateBlock icon={Wallet} title={t('noPositions')} />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('column.stock')}</TableHead>
              <TableHead className="text-right">{t('column.quantity')}</TableHead>
              <TableHead className="text-right">{t('column.averageCost')}</TableHead>
              <TableHead className="text-right">{t('column.markPrice')}</TableHead>
              <TableHead>{t('column.markedAt')}</TableHead>
              <TableHead className="text-right">{t('column.marketValue')}</TableHead>
              <TableHead className="text-right">{t('column.unrealized')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {positions.map((position) => (
              <TableRow key={position.stock_id}>
                <TableCell>
                  <Link to={paths.stock(position.stock_id)} className="font-mono hover:text-primary">
                    {position.stock_id}
                  </Link>
                </TableCell>
                <TableCell className="tabular text-right">{formatNumber(locale, position.quantity)}</TableCell>
                <TableCell className="tabular text-right">{formatPrice(locale, position.average_cost)}</TableCell>
                <TableCell className="tabular text-right">{formatPrice(locale, position.mark_price)}</TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {position.marked_at ? `${formatDateTime(locale, position.marked_at)} · ${t(live.has(position.stock_id) ? 'realtime' : 'dailyClose')}` : t('unpriced')}
                </TableCell>
                <TableCell className="tabular text-right">{formatNumber(locale, position.market_value)}</TableCell>
                <TableCell className="text-right">
                  <ChangeValue value={position.unrealized_pnl} format="absolute" />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Panel>
  )
}

function EquityCurve({ history }: { history: AccountHistory }) {
  const { t } = useTranslation('account')
  const locale = useLocale()
  const days = Object.entries(history.equity_curve)
  const first = days[0]
  const last = days.at(-1)
  return (
    <Panel title={t('curveTitle')} aside={first && last && <span className="tabular">{formatDate(locale, first[0])} – {formatDate(locale, last[0])}</span>}>
      {!first || !last ? (
        <p className="text-sm text-muted-foreground">{t('noCurve')}</p>
      ) : (
        <div className="space-y-2">
          <Sparkline values={days.map(([, value]) => value.equity)} direction={directionOf(last[1].equity - first[1].equity)} width={640} height={96} className="h-24 w-full" />
          <p className="tabular text-sm">
            {formatNumber(locale, first[1].equity)} → {formatNumber(locale, last[1].equity)}{' '}
            <ChangeValue value={first[1].equity ? (last[1].equity - first[1].equity) / first[1].equity : 0} format="percent" />
          </p>
        </div>
      )}
    </Panel>
  )
}
