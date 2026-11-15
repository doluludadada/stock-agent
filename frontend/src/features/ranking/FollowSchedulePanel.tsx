import { useId } from 'react'
import { useTranslation } from '@/i18n'
import { useErrorReason } from '@/shared/lib/error-reason'
import { ErrorState } from '@/shared/ui/error-state'
import { Panel } from '@/shared/ui/panel'
import { Segmented } from '@/shared/ui/segmented'
import { Skeleton } from '@/shared/ui/skeleton'
import { useRankingFollow, useScheduleFollow } from './api'
import { clockTime } from './model'

const OFF = 'off'

/** My settings' scheduled follow: whether the site follows each new decision into the mock account by itself, and from what time. */
export function FollowSchedulePanel() {
  const { t } = useTranslation('ranking')
  const reason = useErrorReason()
  const follow = useRankingFollow()
  const save = useScheduleFollow()
  const helpId = useId()
  const schedule = follow.data?.schedule
  return (
    <Panel title={t('schedule.title')}>
      {follow.isError ? (
        <ErrorState error={follow.error} title={t('follow.loadFailed')} onRetry={() => void follow.refetch()} />
      ) : !schedule ? (
        <Skeleton className="h-16" />
      ) : (
        <div className="space-y-3">
          <Segmented
            label={t('schedule.title')}
            describedBy={helpId}
            value={schedule.time ?? OFF}
            onChange={(chosen) => save.mutate(chosen === OFF ? null : chosen)}
            options={[{ value: OFF, label: t('schedule.offChoice') }, ...schedule.times.map((time) => ({ value: time, label: clockTime(time) }))]}
          />
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
