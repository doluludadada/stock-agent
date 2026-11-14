import { LoaderCircle, Play } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { useTranslation } from '@/i18n'
import { isApiError } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { useErrorReason } from '@/shared/lib/error-reason'
import { useFormat } from '@/shared/lib/format'
import { Button } from '@/shared/ui/button'
import { Field } from '@/shared/ui/field'
import { Input } from '@/shared/ui/input'
import { Panel } from '@/shared/ui/panel'
import { useRunBacktest, useRunFailure } from './api'
import { parseDraft, periodPresets, refusedFields, SCORE_RANGE, type Bounds, type Draft, type DraftField } from './model'

interface BacktestFormProps {
  strategyName: string
  bounds: Bounds
  draft: Draft
  onDraft: (draft: Draft) => void
  /** A backtest is running, started here or before the page was left and opened again. */
  running: boolean
  /** The buy score of the backtest on screen when it bought nothing; the field then says what to try. */
  noTradesAt: number | null
  onDone: (backtestId: string) => void
}

/** What to backtest: the period within the days available, the starting cash and the two scores, on the active strategy. */
export function BacktestForm({ strategyName, bounds, draft, onDraft, running, noTradesAt, onDone }: BacktestFormProps) {
  const { t } = useTranslation('backtest')
  const format = useFormat()
  const reason = useErrorReason()
  const run = useRunBacktest()
  const failure = useRunFailure()
  const [attempted, setAttempted] = useState(false)
  const parsed = parseDraft(draft, bounds)
  const available = { first: format.date(bounds.first), last: format.date(bounds.last) }

  const refusal = isApiError(failure.error) ? failure.error : null
  const periodRefused = refusal?.code === 'backtest_period_unavailable'
  const refused = refusal ? refusedFields(refusal.problems) : []
  const failed = failure.error !== null && !periodRefused && refused.length === 0

  const problem = (field: DraftField): string | null => {
    const found = attempted && !parsed.ok ? parsed.problems[field] : undefined
    return found ? t(`problem.${found}`, { ...available, ...SCORE_RANGE }) : refused.includes(field) ? t('common:errors.invalid') : null
  }
  const change = (field: DraftField, value: string) => {
    if (failure.error) failure.dismiss()
    onDraft({ ...draft, [field]: value })
  }
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setAttempted(true)
    if (!parsed.ok || running) return
    run.mutate(parsed.inputs, { onSuccess: (backtest) => onDone(backtest.backtest_id) })
  }

  return (
    <Panel title={t('form.title')}>
      <form onSubmit={submit} noValidate className="space-y-4">
        <p className="rounded-lg bg-muted px-3 py-2.5 text-sm">
          <span className="block text-xs text-muted-foreground">{t('form.strategy')}</span>
          <span className="flex flex-wrap items-baseline justify-between gap-x-3">
            <span className="font-medium">{strategyName}</span>
            <Link to={paths.strategies} className="tap text-xs text-brand underline-offset-4 hover:underline">
              {t('form.changeStrategy')}
            </Link>
          </span>
        </p>

        <fieldset className="space-y-3">
          <legend className="mb-2 text-sm font-medium">{t('form.period')}</legend>
          <div className="flex flex-wrap gap-1.5">
            {periodPresets(bounds).map((preset) => {
              const chosen = draft.first === preset.first && draft.last === preset.last
              return (
                <Button
                  key={preset.key}
                  type="button"
                  size="sm"
                  variant={chosen ? 'secondary' : 'outline'}
                  aria-pressed={chosen}
                  onClick={() => {
                    if (failure.error) failure.dismiss()
                    onDraft({ ...draft, first: preset.first, last: preset.last })
                  }}
                >
                  {t(`preset.${preset.key}`)}
                </Button>
              )
            })}
          </div>
          <div className="grid grid-cols-2 items-start gap-3">
            <Field label={t('form.first')} error={problem('first')}>
              <Input type="date" min={bounds.first} max={bounds.last} value={draft.first} onChange={(event) => change('first', event.target.value)} />
            </Field>
            <Field label={t('form.last')} error={problem('last')}>
              <Input type="date" min={bounds.first} max={bounds.last} value={draft.last} onChange={(event) => change('last', event.target.value)} />
            </Field>
          </div>
          {periodRefused ? (
            <p role="alert" className="text-xs text-destructive">
              {t('refusal.period', available)}
            </p>
          ) : (
            <p className="text-xs text-muted-foreground">{t('form.available', available)}</p>
          )}
        </fieldset>

        <Field label={t('form.cash')} error={problem('cash')}>
          <Input type="number" inputMode="decimal" min={1} step="any" value={draft.cash} onChange={(event) => change('cash', event.target.value)} />
        </Field>

        <div className="grid grid-cols-2 items-start gap-3">
          <Field
            label={t('form.buy')}
            error={problem('buy')}
            hint={noTradesAt !== null ? <span className="text-gold">{t('form.buyAfterNoTrades', { score: noTradesAt })}</span> : t('form.buyHint')}
          >
            <Input type="number" inputMode="numeric" min={SCORE_RANGE.min} max={SCORE_RANGE.max} step={1} value={draft.buy} onChange={(event) => change('buy', event.target.value)} />
          </Field>
          <Field label={t('form.sell')} error={problem('sell')} hint={t('form.sellHint')}>
            <Input type="number" inputMode="numeric" min={SCORE_RANGE.min} max={SCORE_RANGE.max} step={1} value={draft.sell} onChange={(event) => change('sell', event.target.value)} />
          </Field>
        </div>

        {failed && (
          <p role="alert" className="rounded-lg bg-danger-soft px-3 py-2.5 text-sm text-destructive">
            {t('refusal.failed', { reason: reason(failure.error) })}
          </p>
        )}

        <Button type="submit" className="w-full" disabled={running}>
          {running ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <Play aria-hidden />}
          {running ? t('form.running') : t('form.run')}
        </Button>
        <p className="text-xs text-pretty text-muted-foreground">{t('form.safe')}</p>
      </form>
    </Panel>
  )
}
