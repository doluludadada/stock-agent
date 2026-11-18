import { useId } from 'react'
import { useTranslation } from '@/i18n'
import { useAccountLabel } from '@/shared/api'
import { useErrorReason } from '@/shared/lib/error-reason'
import { clockTime } from '@/shared/lib/format'
import { ErrorState } from '@/shared/ui/error-state'
import { Panel } from '@/shared/ui/panel'
import { fitsSegmented, Segmented } from '@/shared/ui/segmented'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/ui/select'
import { Skeleton } from '@/shared/ui/skeleton'
import { useChooseFollowAccount, useFollowSettings, useScheduleFollow } from './api'
import { accountChoices, offeredTimes } from './model'

const OFF = 'off'

/**
 * My settings' ranking follow, from one answer of the server, as two controls that each save alone: the follow
 * account, the one account the ranking page's button and the schedule follow on, shown where the viewer may have more
 * than one; and whether the site follows each new decision by itself there, from what time. While the server refuses
 * the account, the time's help says the site follows on no account and why, never the account it would follow on.
 */
export function FollowSettingsPanel() {
  const { t } = useTranslation('ranking')
  const reason = useErrorReason()
  const label = useAccountLabel()
  const settings = useFollowSettings()
  const chooseAccount = useChooseFollowAccount()
  const saveTime = useScheduleFollow()
  const accountHelpId = useId()
  const timeHelpId = useId()
  const failed = chooseAccount.error ?? saveTime.error
  if (settings.isError)
    return (
      <Panel title={t('schedule.title')}>
        <ErrorState error={settings.error} title={t('schedule.loadFailed')} onRetry={() => void settings.refetch()} />
      </Panel>
    )
  if (settings.isPending)
    return (
      <Panel title={t('schedule.title')}>
        <Skeleton className="h-16" />
      </Panel>
    )
  const { account, schedule } = settings.data
  const choices = accountChoices(account)
  return (
    <Panel title={t('schedule.title')}>
      <div className="space-y-4">
        {choices.length > 1 && (
          <div className="space-y-1.5">
            <p className="text-sm font-medium">{t('schedule.accountLabel')}</p>
            <Choice
              label={t('schedule.accountLabel')}
              describedBy={accountHelpId}
              value={account.broker}
              options={choices.map((broker) => ({ value: broker, label: label(broker, account.server) }))}
              onChange={(broker) => chooseAccount.mutate(broker)}
            />
            <div id={accountHelpId} className="space-y-1 text-sm text-pretty text-muted-foreground">
              <p>{t('schedule.accountHelp')}</p>
              {account.refusal !== null && <p className="text-foreground">{t('schedule.notOffered')}</p>}
            </div>
          </div>
        )}
        <div className="space-y-1.5">
          <p className="text-sm font-medium">{t('schedule.timeLabel')}</p>
          <Choice
            label={t('schedule.timeLabel')}
            describedBy={timeHelpId}
            value={schedule.time ?? OFF}
            options={[{ value: OFF, label: t('schedule.offChoice') }, ...offeredTimes(schedule).map((time) => ({ value: time, label: clockTime(time) }))]}
            onChange={(chosen) => saveTime.mutate(chosen === OFF ? null : chosen)}
          />
          <p id={timeHelpId} className="text-sm text-pretty text-muted-foreground">
            {account.refusal === null
              ? t('schedule.help', { account: label(account.broker, account.server) })
              : t('schedule.helpRefused', { why: t(`common:refusal.${account.refusal}`) })}
          </p>
        </div>
        {failed && (
          <p role="alert" className="text-sm text-destructive">
            {t('schedule.failed', { reason: reason(failed) })}
          </p>
        )}
      </div>
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

/** One of the panel's choices: a row of buttons while its options fit a phone's row, a list otherwise. */
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
