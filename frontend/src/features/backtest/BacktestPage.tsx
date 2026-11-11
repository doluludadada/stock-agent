import { CalendarX, FlaskConical, LoaderCircle, SearchX } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { useTranslation } from '@/i18n'
import { isApiError } from '@/shared/api'
import { Button } from '@/shared/ui/button'
import { ErrorState } from '@/shared/ui/error-state'
import { PageHeader } from '@/shared/ui/page-header'
import { Panel } from '@/shared/ui/panel'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { Skeleton } from '@/shared/ui/skeleton'
import { StateBlock } from '@/shared/ui/state-block'
import { useBacktest, useBacktestOptions, useRunningSince } from './api'
import { BacktestForm } from './BacktestForm'
import { BacktestResult, ReadingNotes } from './BacktestResult'
import { draftOf, type Draft } from './model'
import { SavedBacktests } from './SavedBacktests'

/** Would the active strategy have made money over a past period: the form, the answer, and the earlier answers to compare. */
export function BacktestPage() {
  const { t } = useTranslation('backtest')
  return (
    <div className="space-y-5 lg:space-y-6">
      <PageHeader eyebrow={t('common:nav.section.analysis')} title={t('page.title')} description={t('page.description')} />
      <RequireSignIn layout="page" reason={t('signIn')}>
        <Workbench />
      </RequireSignIn>
    </div>
  )
}

/**
 * The form beside the result from 1280 px, above it when narrower; the saved backtests across. The backtest on screen
 * is the address's `id`, so a saved one can be opened, reloaded and gone back to. The form keeps what was typed
 * through every run.
 */
function Workbench() {
  const { t } = useTranslation('backtest')
  const [params, setParams] = useSearchParams()
  const shownId = params.get('id')
  const options = useBacktestOptions()
  const shown = useBacktest(shownId)
  const runningSince = useRunningSince()
  const [typed, setTyped] = useState<Draft | null>(null)
  const show = (id: string | null) => setParams(id ? { id } : {})

  const defaults = options.data?.inputs ?? null
  const noTradesAt = shown.data && shown.data.trade_count === 0 ? shown.data.inputs.buy_score : null

  return (
    <div className="grid items-start gap-4 lg:gap-5 xl:grid-cols-[22rem_minmax(0,1fr)]">
      {options.isPending ? (
        <Skeleton className="h-96 rounded-2xl" />
      ) : options.isError ? (
        <ErrorState error={options.error} title={t('form.loadFailed')} onRetry={() => void options.refetch()} className="rounded-2xl border bg-card py-12" />
      ) : defaults === null ? (
        <Panel title={t('form.title')}>
          <StateBlock icon={CalendarX} title={t('tooShort.title')} description={t('tooShort.description', { strategy: options.data.strategy_name })} />
        </Panel>
      ) : (
        <BacktestForm
          strategyName={options.data.strategy_name}
          bounds={defaults}
          draft={typed ?? draftOf(defaults)}
          onDraft={setTyped}
          running={runningSince !== null}
          noTradesAt={noTradesAt}
          onDone={show}
        />
      )}

      <div className="min-w-0 space-y-4 lg:space-y-5">
        {runningSince !== null && <RunProgress since={runningSince} />}
        {shownId === null ? (
          runningSince === null && (
            <>
              <Panel>
                <StateBlock icon={FlaskConical} title={t('empty.title')} description={t('empty.description')} />
              </Panel>
              <ReadingNotes />
            </>
          )
        ) : shown.isPending ? (
          <Skeleton className="h-96 rounded-2xl" />
        ) : shown.isError ? (
          isApiError(shown.error, 'notFound') ? (
            <Panel>
              <StateBlock
                icon={SearchX}
                title={t('gone.title')}
                description={t('gone.description')}
                action={
                  <Button type="button" variant="outline" size="sm" onClick={() => show(null)}>
                    {t('gone.close')}
                  </Button>
                }
              />
            </Panel>
          ) : (
            <ErrorState error={shown.error} title={t('result.loadFailed')} onRetry={() => void shown.refetch()} className="rounded-2xl border bg-card py-12" />
          )
        ) : (
          <BacktestResult
            key={shown.data.backtest_id}
            backtest={shown.data}
            onReuse={() => setTyped(draftOf(shown.data.inputs))}
            onTryBuyScore={(score) => setTyped({ ...(typed ?? draftOf(shown.data.inputs)), buy: String(score) })}
          />
        )}
      </div>

      <SavedBacktests className="xl:col-span-2" shownId={shownId} onDeleted={(id) => id === shownId && show(null)} />
    </div>
  )
}

/** A run takes from under a second to tens of seconds: the seconds so far, and why the first one is the slow one. */
function RunProgress({ since }: { since: number }) {
  const { t } = useTranslation('backtest')
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  const seconds = Math.max(0, Math.floor((now - since) / 1000))
  return (
    <output className="flex items-start gap-3 rounded-2xl border border-primary/30 bg-brand-soft px-4 py-3.5 text-sm">
      <LoaderCircle aria-hidden className="mt-0.5 size-4 shrink-0 animate-spin text-brand motion-reduce:animate-none" />
      <div className="min-w-0 space-y-0.5">
        <p className="font-medium">{t('progress.title', { seconds })}</p>
        <p className="text-pretty text-muted-foreground">{t('progress.hint')}</p>
      </div>
    </output>
  )
}
