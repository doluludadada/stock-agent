import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { useTranslation } from '@/i18n'
import { useListedNames } from '@/shared/api'
import { sessionDate } from '@/shared/lib/chart-range'
import { useErrorReason } from '@/shared/lib/error-reason'
import { useFormat } from '@/shared/lib/format'
import { Button } from '@/shared/ui/button'
import { StockName } from '@/shared/ui/stock-name'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/shared/ui/dialog'
import { Field } from '@/shared/ui/field'
import { Input } from '@/shared/ui/input'
import { StockPicker } from '@/shared/ui/stock-picker'
import { entryRefusalOf, useEnterHolding } from './api'
import { AVERAGE_COST_MAX, parseEntry, QUANTITY_MAX, type EntryDraft, type EntryField } from './model'

/** What the entry form opens on: an empty draft, a watched stock already chosen, or an entry to change. */
export interface EntrySeed {
  draft: EntryDraft
  /** A change keeps its stock: the save replaces the entry of that stock. */
  replaces: boolean
}

/** The hand-entry form. It notes shares held elsewhere: it orders nothing and touches no account. */
export function HoldingDialog({ seed, onClose }: { seed: EntrySeed | null; onClose: () => void }) {
  const { t } = useTranslation('holdings')
  return (
    <Dialog open={seed !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="gap-5 sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="text-title">{t(seed?.replaces ? 'form.changeTitle' : 'form.addTitle')}</DialogTitle>
          <DialogDescription className="text-pretty">{t('form.description')}</DialogDescription>
        </DialogHeader>
        {seed && <EntryForm seed={seed} onClose={onClose} />}
      </DialogContent>
    </Dialog>
  )
}

/** The dialog's body; it mounts each time the dialog opens, so nothing typed before comes back. */
function EntryForm({ seed, onClose }: { seed: EntrySeed; onClose: () => void }) {
  const { t } = useTranslation('holdings')
  const format = useFormat()
  const reason = useErrorReason()
  const enter = useEnterHolding()
  const [draft, setDraft] = useState(seed.draft)
  const [checked, setChecked] = useState(false)
  const [today] = useState(() => sessionDate(new Date().toISOString()))
  const names = useListedNames(draft.stockId ? [draft.stockId] : [])
  const parsed = parseEntry(draft, today)
  const refusal = enter.isError ? entryRefusalOf(enter.error) : null
  const bounds = { quantity: format.number(QUANTITY_MAX), averageCost: format.number(AVERAGE_COST_MAX) }
  const problem = (field: EntryField) => (checked && parsed.problems?.includes(field) ? t(`form.problem.${field}`, bounds) : null)
  const stockProblem = problem('stockId') ?? (refusal === 'unlisted' ? t('form.refusal.unlisted', { code: draft.stockId }) : null)
  const set = (change: Partial<EntryDraft>) => {
    enter.reset()
    setDraft({ ...draft, ...change })
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (!parsed.entry || enter.isPending) return
    const { stock_id } = parsed.entry
    enter.mutate(parsed.entry, {
      onSuccess: () => {
        toast.success(t('form.saved', { name: names.get(stock_id) ?? stock_id }))
        onClose()
      },
    })
  }

  return (
    <form onSubmit={submit} noValidate className="grid gap-4">
      <fieldset className="grid gap-1.5">
        <legend className="mb-1.5 text-sm leading-none font-medium">{t('form.stock')}</legend>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          {draft.stockId && (
            <StockName stockId={draft.stockId} name={names.get(draft.stockId)} className="text-sm" />
          )}
          {!seed.replaces && <StockPicker label={t(draft.stockId ? 'form.changeStock' : 'form.chooseStock')} onSelect={(stockId) => set({ stockId })} />}
        </div>
        {stockProblem && (
          <p role="alert" className="text-xs text-destructive">
            {stockProblem}
          </p>
        )}
      </fieldset>
      <Field label={t('form.quantity')} hint={t('form.quantityHint')} error={problem('quantity')}>
        <Input inputMode="numeric" autoComplete="off" value={draft.quantity} onChange={(event) => set({ quantity: event.target.value })} />
      </Field>
      <Field label={t('form.averageCost')} error={problem('averageCost')}>
        <Input inputMode="decimal" autoComplete="off" value={draft.averageCost} onChange={(event) => set({ averageCost: event.target.value })} />
      </Field>
      <Field label={t('form.openedOn')} error={problem('openedOn')}>
        <Input type="date" max={today} value={draft.openedOn} onChange={(event) => set({ openedOn: event.target.value })} />
      </Field>
      {refusal === 'failed' && (
        <p role="alert" className="text-sm text-pretty text-destructive">
          {t('form.refusal.failed', { reason: reason(enter.error) })}
        </p>
      )}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          {t('form.cancel')}
        </Button>
        <Button type="submit" disabled={enter.isPending}>
          {t(enter.isPending ? 'form.saving' : 'form.save')}
        </Button>
      </DialogFooter>
    </form>
  )
}
