import { History as HistoryIcon, RotateCcw } from 'lucide-react'
import { useId, useState } from 'react'
import { useLocale, useTranslation } from '@/i18n'
import { formatMonthDayTime } from '@/shared/lib/format'
import { cn } from '@/shared/lib/utils'
import { Button } from '@/shared/ui/button'
import { ErrorState } from '@/shared/ui/error-state'
import { Panel } from '@/shared/ui/panel'
import { ShowMore } from '@/shared/ui/show-more'
import { Skeleton } from '@/shared/ui/skeleton'
import { useRestoreBackup, useRestorePreview, useSettingsAudit, useSettingsBackups } from './api'
import { historyOf, refusalOf, type AuditEntry, type SettingsBackup, type SettingsEdit, type SettingsFileId } from './model'
import { ReviewDialog, type DialogRefusal } from './ReviewDialog'

/** Changes listed before the rest is asked for. */
const SHOWN = 5

interface HistoryProps {
  file: SettingsFileId
  /** The revision on disk now: a restore is checked and sent against it. */
  revision: string
  /** The signed-in administrator, named "you" in the list. */
  me: string
  /** Why a restore cannot start now, such as unsaved changes to this file; null when it can. */
  blocked: string | null
  throttledUntil: number | null
  onThrottled: (until: number) => void
  /** A restore went through, or the page must answer its refusal (a conflict, a version the app would not start with). */
  onRestored: (edit: SettingsEdit, version: string) => void
  onRefused: (refusal: ReturnType<typeof refusalOf>) => void
}

/**
 * Who changed this file from the page and when, newest first: each save or restore with the settings it changed, and
 * the version it replaced while that backup is kept, which can be compared with the file on disk and restored.
 */
export function History({ file, revision, me, blocked, throttledUntil, onThrottled, onRestored, onRefused }: HistoryProps) {
  const { t } = useTranslation('admin')
  const locale = useLocale()
  const backups = useSettingsBackups(file)
  const audit = useSettingsAudit()
  const [chosen, setChosen] = useState<SettingsBackup | null>(null)
  const [expanded, setExpanded] = useState(false)
  const listId = useId()

  const failed = backups.error ?? audit.error
  /** After a save the audit and the backups are read again: until they answer, the list is the one before the save. */
  const refreshing = backups.isFetching || audit.isFetching
  const { changes, unmatched } = historyOf(file, backups.data ?? [], audit.data ?? [])
  const total = changes.length + unmatched.length
  /** The newest change made the file on disk now; an older one with the same text is history, as is any after an edit on disk. */
  const current = changes[0]?.entry.to_revision === revision
  const shownChanges = expanded ? changes : changes.slice(0, SHOWN)
  const shownUnmatched = expanded ? unmatched : unmatched.slice(0, Math.max(0, SHOWN - changes.length))
  const body = (() => {
    if (backups.isPending || audit.isPending) return <Skeleton className="h-32 rounded-lg" />
    if (failed) return <ErrorState error={failed} title={t('history.failed')} onRetry={() => void Promise.all([backups.refetch(), audit.refetch()])} className="py-6" />
    if (total === 0) return <p className="text-sm text-pretty text-muted-foreground">{t('history.empty')}</p>
    return (
      <ol
        id={listId}
        aria-busy={refreshing}
        className={cn('relative space-y-1 transition-opacity before:absolute before:top-3 before:bottom-3 before:left-[0.4375rem] before:w-px before:bg-border', refreshing && 'opacity-60')}
      >
        {shownChanges.map(({ entry, before }, index) => (
          <li key={`${entry.recorded_at}-${entry.to_revision}`} className="relative pl-6">
            <span aria-hidden className={cn('absolute top-2.5 left-0.5 size-2.5 rounded-full border-2 border-card', index === 0 && current ? 'bg-brand' : 'bg-line-strong')} />
            <ChangeRow entry={entry} me={me} current={index === 0 && current} locale={locale} />
            {before ? (
              <Button type="button" variant="ghost" size="sm" className="-ml-2.5 text-brand" onClick={() => setChosen(before)} disabled={refreshing}>
                <RotateCcw aria-hidden />
                {t('history.viewBefore')}
              </Button>
            ) : (
              <p className="pb-2 text-xs text-faint">{t('history.noBackup')}</p>
            )}
          </li>
        ))}
        {shownUnmatched.map((backup) => (
          <li key={backup.backup_id} className="relative flex flex-wrap items-center justify-between gap-2 pl-6">
            <span aria-hidden className="absolute top-3.5 left-0.5 size-2.5 rounded-full border-2 border-card bg-line-strong" />
            <span className="text-sm">
              {t('history.kept')} <span className="tabular text-muted-foreground">{formatMonthDayTime(locale, backup.created_at)}</span>
            </span>
            <Button type="button" variant="ghost" size="sm" className="text-brand" onClick={() => setChosen(backup)} disabled={refreshing}>
              {t('history.view')}
            </Button>
          </li>
        ))}
      </ol>
    )
  })()

  return (
    <Panel
      title={
        <>
          <HistoryIcon aria-hidden className="size-4 text-muted-foreground" />
          {t('history.title')}
        </>
      }
      description={t('history.description')}
      footer={
        total > SHOWN && (
          <ShowMore expanded={expanded} onToggle={() => setExpanded(!expanded)} controls={listId} moreLabel={t('history.showAll', { count: total })} lessLabel={t('history.showLess')} />
        )
      }
    >
      {body}
      {chosen && (
        <RestoreDialog
          key={chosen.backup_id}
          file={file}
          backup={chosen}
          revision={revision}
          blocked={blocked}
          onClose={() => setChosen(null)}
          throttledUntil={throttledUntil}
          onThrottled={onThrottled}
          onRestored={(edit) => {
            setChosen(null)
            onRestored(edit, formatMonthDayTime(locale, chosen.created_at))
          }}
          onRefused={(refusal) => {
            setChosen(null)
            onRefused(refusal)
          }}
        />
      )}
    </Panel>
  )
}

function ChangeRow({ entry, me, current, locale }: { entry: AuditEntry; me: string; current: boolean; locale: string }) {
  const { t } = useTranslation('admin')
  const name = entry.actor_name ?? t('history.unknown')
  const title =
    entry.actor === me ? t(entry.action === 'restore' ? 'history.youRestored' : 'history.youSaved') : t(entry.action === 'restore' ? 'history.restored' : 'history.saved', { name })
  const shown = entry.settings.slice(0, 3)
  return (
    <div className="py-1.5">
      <p className="flex flex-wrap items-baseline gap-x-2 text-sm">
        <span className="font-medium">{title}</span>
        <time dateTime={entry.recorded_at} className="tabular text-xs text-muted-foreground">
          {formatMonthDayTime(locale, entry.recorded_at)}
        </time>
        {current && <span className="rounded-full bg-brand-soft px-2 py-0.5 text-xs font-medium text-brand">{t('history.current')}</span>}
      </p>
      {entry.settings.length === 0 ? (
        <p className="text-xs text-muted-foreground">{t('history.noSettings')}</p>
      ) : (
        <p className="mt-0.5 flex flex-wrap gap-1">
          {shown.map((setting) => (
            <code key={setting} className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs break-all">
              {setting}
            </code>
          ))}
          {entry.settings.length > shown.length && <span className="text-xs text-muted-foreground">{t('history.more', { count: entry.settings.length - shown.length })}</span>}
        </p>
      )}
    </div>
  )
}

interface RestoreDialogProps {
  file: SettingsFileId
  backup: SettingsBackup
  revision: string
  blocked: string | null
  onClose: () => void
  throttledUntil: number | null
  onThrottled: (until: number) => void
  onRestored: (edit: SettingsEdit) => void
  onRefused: (refusal: ReturnType<typeof refusalOf>) => void
}

/** A kept version against the file on disk, checked as a save; restoring it goes through the same checks. */
function RestoreDialog({ file, backup, revision, blocked, onClose, throttledUntil, onThrottled, onRestored, onRefused }: RestoreDialogProps) {
  const { t } = useTranslation('admin')
  const locale = useLocale()
  const preview = useRestorePreview(file, backup.backup_id, revision)
  const restore = useRestoreBackup(file)
  const edit = preview.data
  const reason =
    blocked ??
    (edit && edit.problems.length > 0 ? t('history.restoreProblems') : null) ??
    (edit && edit.revision === edit.base_revision ? t('history.restoreSame') : null)

  const confirm = async (password: string): Promise<DialogRefusal | null> => {
    try {
      onRestored(await restore.mutateAsync({ backupId: backup.backup_id, revision, password }))
      return null
    } catch (error) {
      const refusal = refusalOf(error)
      if (refusal.kind === 'conflict' || refusal.kind === 'refused') {
        onRefused(refusal)
        return null
      }
      return refusal
    }
  }

  return (
    <ReviewDialog
      open
      onOpenChange={(open) => !open && onClose()}
      title={t('history.restoreTitle', { time: formatMonthDayTime(locale, backup.created_at) })}
      description={t('history.restoreDescription', { file: t(`file.${file}`) })}
      confirmLabel={t('history.restoreConfirm')}
      showLines
      review={preview.isPending ? { kind: 'loading' } : preview.isError ? { kind: 'failed', error: preview.error } : { kind: 'ready', edit: preview.data }}
      blocked={reason}
      onConfirm={confirm}
      throttledUntil={throttledUntil}
      onThrottled={onThrottled}
    />
  )
}
