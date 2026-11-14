import { useTranslation } from '@/i18n'
import { useFormat } from '@/shared/lib/format'
import { Panel } from '@/shared/ui/panel'
import { CAVEATS, idleDecisions, type RankingBacktest } from './model'

/** What the backtest's figures leave out: the costs it took off, the months it sat out, and what the research measured about trusting it. */
export function Caveats({ backtest }: { backtest: RankingBacktest }) {
  const { t } = useTranslation('ranking')
  const format = useFormat()
  const idle = idleDecisions(backtest)
  return (
    <Panel title={t('caveats.title')}>
      <ul className="list-disc space-y-1.5 pl-5 text-sm text-pretty marker:text-gold">
        {CAVEATS.map((caveat) => (
          <li key={caveat}>
            <span className="font-medium">{t(`caveats.${caveat}.title`)}</span> <span className="text-muted-foreground">{t(`caveats.${caveat}.detail`)}</span>
          </li>
        ))}
        <li className="text-muted-foreground">{t('record.costs', { costs: format.percent(backtest.costs), fee: format.percent(backtest.fee_rate, 4), tax: format.percent(backtest.tax_rate, 1) })}</li>
        {backtest.benchmark_total_return === null && <li className="text-muted-foreground">{t('record.noBenchmark', { benchmark: backtest.benchmark_id })}</li>}
        {idle > 0 && <li className="text-muted-foreground">{t('record.idle', { count: idle })}</li>}
      </ul>
    </Panel>
  )
}
