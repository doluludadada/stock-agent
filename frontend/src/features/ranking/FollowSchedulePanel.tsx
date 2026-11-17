import { useId } from 'react'
import { useTranslation } from '@/i18n'
import { useErrorReason } from '@/shared/lib/error-reason'
import { clockTime } from '@/shared/lib/format'
import { ErrorState } from '@/shared/ui/error-state'
import { Panel } from '@/shared/ui/panel'
import { fitsSegmented, Segmented } from '@/shared/ui/segmented'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/ui/select'
import { Skeleton } from '@/shared/ui/skeleton'
import { useFollowSchedule, useScheduleFollow } from './api'
import { offeredBrokers, offeredTimes } from './model'

const OFF = 'off'

/**
 * My settings' scheduled follow: whether the site follows each new decision by itself, from what time, and, where the
 * site offers more than the mock account, on which account.
 */
export function FollowSchedulePanel() {
  const { t } = useTranslation('ranking')
  const reason = useErrorReason()
  const answer = useFollowSchedule()
  const save = useScheduleFollow()
  const helpId = useId()
  const accountHelpId = useId()
  const schedule = answer.data
  return (
    <Panel title={t('schedule.title')}>
      {answer.isError ? (
        <ErrorState error={answer.error} title={t('schedule.loadFailed')} onRetry={() => void answer.refetch()} />
      ) : !schedule ? (
        <Skeleton className="h-16" />
      ) : (
        <div className="space-y-3">
          <Choice
            label={t('schedule.title')}
            describedBy={helpId}
            value={schedule.time ?? OFF}
            options={[{ value: OFF, label: t('schedule.offChoice') }, ...offeredTimes(schedule).map((time) => ({ value: time, label: clockTime(time) }))]}
            onChange={(chosen) => save.mutate({ time: chosen === OFF ? null : chosen, broker: schedule.broker })}
          />
          <p id={helpId} className="text-sm text-pretty text-muted-foreground">
            {t(offeredBrokers(schedule).length > 1 ? 'schedule.helpChosen' : 'schedule.help')}
          </p>
          {offeredBrokers(schedule).length > 1 && (
            <div className="space-y-1.5">
              <p className="text-sm font-medium">{t('schedule.accountLabel')}</p>
              <Choice
                label={t('schedule.accountLabel')}
                describedBy={accountHelpId}
                value={schedule.broker}
                options={offeredBrokers(schedule).map((broker) => ({ value: broker, label: t(`account.${broker}`) }))}
                onChange={(broker) => save.mutate({ time: schedule.time, broker })}
              />
              <div id={accountHelpId} className="space-y-1 text-sm text-pretty text-muted-foreground">
                <p>{t('schedule.accountHelp')}</p>
                {!schedule.broker_offered && <p className="text-foreground">{t(`schedule.notOffered.${schedule.broker}`)}</p>}
              </div>
            </div>
          )}
          {save.isError && (
            <p role="alert" className="text-sm text-destructive">
              {t('schedule.failed', { reason: reason(save.error) })}
            </p>
          )}
        </div>
      )}
    </Panel>
  )
}

interface ChoiceProps<T extends string> {
  label: string
  describedBy: string
  value: T
  options: readonly { value: T; label: string }[]
  onChange: (value: T) => void
}

/** One of the schedule's choices: a row of buttons while its options fit a phone's row, a list otherwise. */
function Choice<T extends string>({ label, describedBy, value, options, onChange }: ChoiceProps<T>) {
  if (fitsSegmented(options.map((option) => option.label))) return <Segmented label={label} describedBy={describedBy} value={value} onChange={onChange} options={options} />
  return (
    <Select value={value} onValueChange={(next) => onChange(next as T)}>
      <SelectTrigger aria-label={label} aria-describedby={describedBy} className="tabular w-full @md:w-64">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value} className="tabular">
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
