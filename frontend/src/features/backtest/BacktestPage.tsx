import { CalendarX, FlaskConical, SearchX } from 'lucide-react'
import { useState } from 'react'
import { useSearchParams } from 'react-router'
import { useTranslation } from '@/i18n'
import { isApiError } from '@/shared/api'
import { Button } from '@/shared/ui/button'
import { ErrorState } from '@/shared/ui/error-state'
import { PageHeader } from '@/shared/ui/page-header'
import { TechnicalStrategyNote } from '@/shared/ui/technical-strategy-note'
import { Panel } from '@/shared/ui/panel'
import { ProgressNote } from '@/shared/ui/progress-note'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { PageSkeleton } from '@/shared/ui/skeleton'
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
    <div className="page-stack">
      <PageHeader title={t('page.title')} description={t('page.description')} note={<TechnicalStrategyNote />} />
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
    <div className="card-grid xl:grid-cols-[22rem_minmax(0,1fr)]">
      {options.isPending ? (
        <PageSkeleton />
      ) : options.isError ? (
        <ErrorState error={options.error} title={t('form.loadFailed')} onRetry={() => void options.refetch()} framed />
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

      <div className="card-stack">
        {runningSince !== null && <ProgressNote since={runningSince} title={(seconds) => t('progress.title', { seconds })} hint={t('progress.hint')} />}
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
          <PageSkeleton />
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
            <ErrorState error={shown.error} title={t('result.loadFailed')} onRetry={() => void shown.refetch()} framed />
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
