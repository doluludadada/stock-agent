import { ShieldAlert } from 'lucide-react'
import { useTranslation } from '@/i18n'
import { REAL_BROKER, REAL_MONEY, useAccountLabel, type Broker, type BrokerOffer } from '@/shared/api'
import { useFormat } from '@/shared/lib/format'
import { cn } from '@/shared/lib/utils'
import { Segmented } from '@/shared/ui/segmented'

interface BrokerChoiceProps {
  offers: readonly BrokerOffer[]
  value: Broker
  onChange: (broker: Broker) => void
}

/** Which account a run orders on, shown unless the mock account is all there is: a real broker always shows its server and limits. */
export function BrokerChoice({ offers, value, onChange }: BrokerChoiceProps) {
  const { t } = useTranslation('runs')
  const format = useFormat()
  const label = useAccountLabel()
  if (!offers.some((offer) => REAL_BROKER[offer.broker])) return null
  const chosen = offers.find((offer) => offer.broker === value)
  return (
    <div className="grid gap-2">
      <Segmented
        label={t('broker.label')}
        value={value}
        onChange={onChange}
        options={offers.map((offer) => ({ value: offer.broker, label: label(offer.broker, 'server' in offer ? offer.server : null) }))}
        className="md:w-full"
      />
      {chosen && 'server' in chosen && (
        <div className={cn('grid gap-1 rounded-lg border px-3 py-2 text-sm', REAL_MONEY[chosen.server] ? 'border-destructive/40 bg-danger-soft' : 'bg-muted/60')}>
          <p className={cn('flex items-center gap-1.5', REAL_MONEY[chosen.server] && 'font-semibold text-destructive')}>
            {REAL_MONEY[chosen.server] && <ShieldAlert aria-hidden className="size-4 shrink-0" />}
            {t(`broker.server.${chosen.server}`, { name: t(`common:broker.name.${chosen.broker}`) })}
          </p>
          <p className="text-xs text-pretty text-muted-foreground">
            {t('broker.limits', { order: format.number(chosen.max_order_value), daily: format.number(chosen.max_daily_buy_value) })}
          </p>
        </div>
      )}
    </div>
  )
}
