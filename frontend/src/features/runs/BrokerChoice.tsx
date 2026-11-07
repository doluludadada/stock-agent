import { ShieldAlert } from 'lucide-react'
import { useLocale, useTranslation } from '@/i18n'
import type { Broker, BrokerOffer } from '@/shared/api'
import { formatNumber } from '@/shared/lib/format'
import { cn } from '@/shared/lib/utils'
import { Segmented } from '@/shared/ui/segmented'

interface BrokerChoiceProps {
  offers: readonly BrokerOffer[]
  value: Broker
  onChange: (broker: Broker) => void
}

/** Which account a run orders on, offered only when the user may choose more than the mock account. */
export function BrokerChoice({ offers, value, onChange }: BrokerChoiceProps) {
  const { t } = useTranslation('runs')
  const locale = useLocale()
  if (offers.length < 2) return null
  const chosen = offers.find((offer) => offer.broker === value)
  return (
    <div className="grid gap-2">
      <Segmented
        label={t('broker.label')}
        value={value}
        onChange={onChange}
        options={offers.map((offer) => ({ value: offer.broker, label: t(`common:broker.name.${offer.broker}`) }))}
        className="md:w-full"
      />
      {chosen && chosen.broker !== 'mock' && (
        <div className={cn('grid gap-1 rounded-lg border px-3 py-2 text-sm', chosen.simulation ? 'bg-muted/60' : 'border-destructive/40 bg-danger-soft')}>
          <p className={cn('flex items-center gap-1.5', !chosen.simulation && 'font-semibold text-destructive')}>
            {!chosen.simulation && <ShieldAlert aria-hidden className="size-4 shrink-0" />}
            {t(chosen.simulation ? 'broker.server.simulation' : 'broker.server.live', { name: t(`common:broker.name.${chosen.broker}`) })}
          </p>
          <p className="text-xs text-pretty text-muted-foreground">
            {t('broker.limits', { order: formatNumber(locale, chosen.max_order_value), daily: formatNumber(locale, chosen.max_daily_buy_value) })}
          </p>
        </div>
      )}
    </div>
  )
}
