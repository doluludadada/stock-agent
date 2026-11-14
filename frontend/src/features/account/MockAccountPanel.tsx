import { useId, useState, type FormEvent } from 'react'
import { useTranslation } from '@/i18n'
import { isApiError } from '@/shared/api'
import { useFormat } from '@/shared/lib/format'
import { Button } from '@/shared/ui/button'
import { ConfirmDialog } from '@/shared/ui/confirm-dialog'
import { ErrorState } from '@/shared/ui/error-state'
import { Label } from '@/shared/ui/label'
import { Panel } from '@/shared/ui/panel'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/ui/select'
import { Stat } from '@/shared/ui/stat'
import { useAccountHistory, useResetAccount, type AccountOpening } from './api'
import { STARTING_CAPITALS, startingCapitalChoices } from './model'

/** My settings' mock account: its starting capital and a reset that opens it again. */
export function MockAccountPanel() {
  const { t } = useTranslation('account')
  const history = useAccountHistory(null)
  if (history.isError) {
    return (
      <Panel title={t('reset.title')}>
        <ErrorState error={history.error} title={t('reset.loadFailed')} onRetry={() => void history.refetch()} />
      </Panel>
    )
  }
  const opening = history.data?.opening
  if (!opening) return null
  return (
    <Panel title={t('reset.title')}>
      <ResetForm opening={opening} />
    </Panel>
  )
}

function ResetForm({ opening }: { opening: AccountOpening }) {
  const { t } = useTranslation('account')
  const format = useFormat()
  const reset = useResetAccount()
  const id = useId()
  const [amount, setAmount] = useState(opening.initial_cash)
  const [confirming, setConfirming] = useState(false)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setConfirming(true)
  }
  const confirm = () => {
    setConfirming(false)
    reset.mutate(amount)
  }
  const status = (): string => {
    if (reset.isPending) return t('reset.resetting')
    if (reset.isSuccess) return t('reset.done', { date: format.dateTime(reset.data.opened_at), cash: format.number(reset.data.initial_cash) })
    if (isApiError(reset.error) && reset.error.code === 'run_in_progress') return t('reset.busy')
    if (reset.isError) return t('reset.failed', { reason: isApiError(reset.error) ? t(`common:errors.${reset.error.kind}`) : '' })
    return ''
  }

  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 gap-4 @md:max-w-md">
        <Stat label={t('reset.capital')}>{format.number(opening.initial_cash)}</Stat>
        <Stat label={t('reset.opened')}>{format.dateTime(opening.opened_at)}</Stat>
      </dl>
      <form onSubmit={submit} className="grid gap-3 @md:max-w-xs">
        <div className="grid gap-1.5">
          <Label htmlFor={id}>{t('reset.label')}</Label>
          <Select value={String(amount)} onValueChange={(value) => setAmount(Number(value))}>
            <SelectTrigger id={id} aria-describedby={`${id}-hint`} className="tabular w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {startingCapitalChoices(opening.initial_cash).map((choice) => (
                <SelectItem key={choice} value={String(choice)} className="tabular">
                  {t(STARTING_CAPITALS.includes(choice) ? 'reset.amount' : 'reset.current', { amount: format.number(choice) })}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p id={`${id}-hint`} className="text-xs text-muted-foreground">
            {t('reset.hint')}
          </p>
        </div>
        <Button type="submit" variant="destructive" className="justify-self-start" disabled={reset.isPending}>
          {t('reset.button')}
        </Button>
      </form>
      <p aria-live="polite" className={reset.isError ? 'text-xs text-destructive' : 'text-xs text-muted-foreground'}>
        {status()}
      </p>
      <ConfirmDialog
        destructive
        open={confirming}
        onOpenChange={setConfirming}
        title={t('reset.confirm.title')}
        description={t('reset.confirm.description')}
        cancel={t('reset.confirm.cancel')}
        confirm={t('reset.confirm.go')}
        onConfirm={confirm}
      >
        <div className="grid gap-3 text-sm">
          <ConsequenceList title={t('reset.confirm.goes')} items={[t('reset.confirm.positions'), t('reset.confirm.cash', { cash: format.number(amount) }), t('reset.confirm.history')]} />
          <ConsequenceList title={t('reset.confirm.stays')} items={[t('reset.confirm.runs'), t('reset.confirm.follow')]} />
        </div>
      </ConfirmDialog>
    </div>
  )
}

function ConsequenceList({ title, items }: { title: string; items: string[] }) {
  return (
    <section className="space-y-1">
      <h3 className="text-xs font-medium text-muted-foreground">{title}</h3>
      <ul className="list-disc space-y-0.5 pl-5">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  )
}
