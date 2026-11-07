import { ShoppingCart } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { useLocale, useTranslation } from '@/i18n'
import { chosenOffer, MOCK_ONLY, useBrokers, type Broker } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { formatNumber } from '@/shared/lib/format'
import { Button } from '@/shared/ui/button'
import { ConfirmDialog } from '@/shared/ui/confirm-dialog'
import { Field } from '@/shared/ui/field'
import { Input } from '@/shared/ui/input'
import { useManualBuy } from './api'
import { BrokerChoice } from './BrokerChoice'
import { parseShares } from './model'
import { useStartRefusal } from './refusal'

interface ManualBuyProps {
  runId: string
  stockId: string
  name: string | null
}

/** A BUY of one stock the specific-stock run reported: the shares, the account where the user may choose, and a yes. */
export function ManualBuy({ runId, stockId, name }: ManualBuyProps) {
  const { t } = useTranslation('runs')
  const locale = useLocale()
  const navigate = useNavigate()
  const buy = useManualBuy(runId)
  const refusal = useStartRefusal()
  const offers = useBrokers().data ?? MOCK_ONLY
  const [open, setOpen] = useState(false)
  const [chosen, setChosen] = useState<Broker>('mock')
  const [shares, setShares] = useState('')
  const broker = chosenOffer(offers, chosen).broker
  const quantity = parseShares(shares)
  const stock = name ? `${stockId} ${name}` : stockId

  const ask = () => {
    setChosen('mock')
    setShares('')
    setOpen(true)
  }
  const confirm = () => {
    if (quantity === null) return
    setOpen(false)
    buy.mutate(
      { stockId, quantity, broker },
      {
        onSuccess: (accepted) => {
          toast.success(t('buy.started', { stock }))
          navigate(paths.run(accepted.run_id))
        },
        onError: (error) => toast.error(refusal(error)),
      },
    )
  }

  return (
    <>
      <Button type="button" variant="outline" size="sm" aria-label={t('buy.label', { stock })} onClick={ask} disabled={buy.isPending}>
        <ShoppingCart aria-hidden />
        {t('buy.button')}
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={t('buy.title', { stock })}
        description={t('buy.description')}
        cancel={t('confirm.cancel')}
        confirm={t('buy.go')}
        confirmDisabled={quantity === null}
        onConfirm={confirm}
      >
        <div className="grid gap-4">
          <Field label={t('buy.shares')} hint={t('buy.sharesHint')} error={shares.trim() !== '' && quantity === null ? t('buy.sharesInvalid') : null}>
            <Input type="number" inputMode="numeric" min={1} step={1} required value={shares} onChange={(event) => setShares(event.target.value)} className="tabular" />
          </Field>
          <BrokerChoice offers={offers} value={broker} onChange={setChosen} />
          {quantity !== null && (
            <p className="tabular text-sm font-medium">
              {t('buy.summary', { stock, shares: formatNumber(locale, quantity), account: t(`common:broker.name.${broker}`) })}
            </p>
          )}
        </div>
      </ConfirmDialog>
    </>
  )
}
