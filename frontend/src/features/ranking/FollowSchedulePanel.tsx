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
import { offeredTimes } from './model'

const OFF = 'off'

/** My settings' scheduled follow: whether the site follows each new decision into the mock account by itself, and from what time. */
export function FollowSchedulePanel() {
  const { t } = useTranslation('ranking')
  const reason = useErrorReason()
  const answer = useFollowSchedule()
  const save = useScheduleFollow()
  const helpId = useId()
  const schedule = answer.data
  const options = schedule ? [{ value: OFF, label: t('schedule.offChoice') }, ...offeredTimes(schedule).map((time) => ({ value: time, label: clockTime(time) }))] : []
  const choose = (chosen: string) => save.mutate(chosen === OFF ? null : chosen)
  return (
    <Panel title={t('schedule.title')}>
      {answer.isError ? (
        <ErrorState error={answer.error} title={t('schedule.loadFailed')} onRetry={() => void answer.refetch()} />
      ) : !schedule ? (
        <Skeleton className="h-16" />
      ) : (
        <div className="space-y-3">
          {fitsSegmented(options.map((option) => option.label)) ? (
            <Segmented label={t('schedule.title')} describedBy={helpId} value={schedule.time ?? OFF} onChange={choose} options={options} />
          ) : (
            <Select value={schedule.time ?? OFF} onValueChange={choose}>
              <SelectTrigger aria-label={t('schedule.title')} aria-describedby={helpId} className="tabular w-full @md:w-64">
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
          )}
          <p id={helpId} className="text-sm text-pretty text-muted-foreground">
            {t('schedule.help')}
          </p>
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
