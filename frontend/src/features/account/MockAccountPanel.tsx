import { useState, type FormEvent } from 'react'
import { useLocale, useTranslation } from '@/i18n'
import { isApiError } from '@/shared/api'
import { formatDateTime, formatNumber } from '@/shared/lib/format'
import { Button } from '@/shared/ui/button'
import { ConfirmDialog } from '@/shared/ui/confirm-dialog'
import { ErrorState } from '@/shared/ui/error-state'
import { Field } from '@/shared/ui/field'
import { Input } from '@/shared/ui/input'
import { Panel } from '@/shared/ui/panel'
import { Stat } from '@/shared/ui/stat'
import { useAccountHistory, useResetAccount, type AccountOpening } from './api'
import { parseStartingCapital } from './model'

/** My settings' mock account: its starting capital and a reset that opens it again. */
export function MockAccountPanel() {
  const { t } = useTranslation('account')
  const history = useAccountHistory('mock', null)
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
    <Panel title={t('reset.title')} description={t('reset.question')}>
      <ResetForm opening={opening} />
    </Panel>
  )
}

function ResetForm({ opening }: { opening: AccountOpening }) {
  const { t } = useTranslation('account')
  const locale = useLocale()
  const reset = useResetAccount()
  const [draft, setDraft] = useState(String(opening.initial_cash))
  const [confirming, setConfirming] = useState(false)
  const amount = parseStartingCapital(draft)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (amount !== null) setConfirming(true)
  }
  const confirm = () => {
    setConfirming(false)
    if (amount !== null) reset.mutate(amount)
  }
  const status = (): string => {
    if (reset.isPending) return t('reset.resetting')
    if (reset.isSuccess) return t('reset.done', { date: formatDateTime(locale, reset.data.opened_at), cash: formatNumber(locale, reset.data.initial_cash) })
    if (isApiError(reset.error) && reset.error.code === 'run_in_progress') return t('reset.busy')
    if (reset.isError) return t('reset.failed', { reason: isApiError(reset.error) ? t(`common:errors.${reset.error.kind}`) : '' })
    return ''
  }

  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 gap-4 @md:max-w-md">
        <Stat label={t('reset.capital')}>{formatNumber(locale, opening.initial_cash)}</Stat>
        <Stat label={t('reset.opened')}>{formatDateTime(locale, opening.opened_at)}</Stat>
      </dl>
      <form onSubmit={submit} className="grid gap-3 @md:max-w-xs">
        <Field label={t('reset.label')} hint={t('reset.hint')} error={draft.trim() !== '' && amount === null ? t('reset.invalid') : null}>
          <Input type="number" inputMode="decimal" min={1} step="any" value={draft} onChange={(event) => setDraft(event.target.value)} className="tabular" />
        </Field>
        <Button type="submit" variant="destructive" className="justify-self-start" disabled={amount === null || reset.isPending}>
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
          <ConsequenceList title={t('reset.confirm.goes')} items={[t('reset.confirm.positions'), t('reset.confirm.cash', { cash: formatNumber(locale, amount ?? 0) }), t('reset.confirm.history')]} />
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
