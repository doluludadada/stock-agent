import { useId } from 'react'
import { useTranslation } from '@/i18n'
import { useErrorReason } from '@/shared/lib/error-reason'
import { ErrorState } from '@/shared/ui/error-state'
import { Panel } from '@/shared/ui/panel'
import { Segmented } from '@/shared/ui/segmented'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/ui/select'
import { Skeleton } from '@/shared/ui/skeleton'
import { useRankingFollow, useScheduleFollow } from './api'
import { clockTime, offeredTimes } from './model'

const OFF = 'off'

/** The most choices a row of buttons shows whole on a phone; more are a list. */
const BUTTONS = 5

/** My settings' scheduled follow: whether the site follows each new decision into the mock account by itself, and from what time. */
export function FollowSchedulePanel() {
  const { t } = useTranslation('ranking')
  const reason = useErrorReason()
  const follow = useRankingFollow()
  const save = useScheduleFollow()
  const helpId = useId()
  const schedule = follow.data?.schedule
  const options = schedule ? [{ value: OFF, label: t('schedule.offChoice') }, ...offeredTimes(schedule).map((time) => ({ value: time, label: clockTime(time) }))] : []
  const choose = (chosen: string) => save.mutate(chosen === OFF ? null : chosen)
  return (
    <Panel title={t('schedule.title')}>
      {follow.isError ? (
        <ErrorState error={follow.error} title={t('follow.loadFailed')} onRetry={() => void follow.refetch()} />
      ) : !schedule ? (
        <Skeleton className="h-16" />
      ) : (
        <div className="space-y-3">
          {options.length <= BUTTONS ? (
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
