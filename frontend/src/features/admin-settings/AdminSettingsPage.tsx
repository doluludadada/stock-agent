import { History, LockKeyhole, RotateCcw, Save, Search, ShieldCheck, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { useLocale, useTranslation } from '@/i18n'
import { isApiError, session, useSession } from '@/shared/api'
import { formatDateTime } from '@/shared/lib/format'
import { cn } from '@/shared/lib/utils'
import { Button } from '@/shared/ui/button'
import { ErrorState } from '@/shared/ui/error-state'
import { Input } from '@/shared/ui/input'
import { Label } from '@/shared/ui/label'
import { PageHeader } from '@/shared/ui/page-header'
import { Panel } from '@/shared/ui/panel'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/ui/select'
import { Skeleton } from '@/shared/ui/skeleton'
import { Switch } from '@/shared/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/shared/ui/tabs'
import { Textarea } from '@/shared/ui/textarea'
import { RequireUnlock } from '@/shared/ui/unlock'
import {
  usePreviewChange,
  usePreviewRestore,
  useRestore,
  useSaveChange,
  useSettingsAudit,
  useSettingsBackups,
  useSettingsFile,
  type SettingsEdit,
  type SettingsFileId,
  type SettingsFilePage,
  type SettingValue,
} from './api'

const FILES: SettingsFileId[] = ['appsetting', 'instructions']

export function AdminSettingsPage() {
  const { t } = useTranslation('admin')
  const { unlocked } = useSession('admin')
  return (
    <div className="space-y-4">
      <PageHeader
        title={t('title')}
        description={t('description')}
        actions={
          unlocked && (
            <Button type="button" variant="outline" size="sm" onClick={() => session.lock('admin')}>
              <LockKeyhole aria-hidden />
              {t('lock')}
            </Button>
          )
        }
      />
      <RequireUnlock scope="admin" className="rounded-xl border">
        <Tabs defaultValue="appsetting" className="gap-4">
          <TabsList>
            {FILES.map((file) => (
              <TabsTrigger key={file} value={file} className="font-mono text-xs">
                {t(`file.${file}`)}
              </TabsTrigger>
            ))}
          </TabsList>
          {FILES.map((file) => (
            <TabsContent key={file} value={file} className="space-y-4">
              <SettingsFileEditor file={file} />
            </TabsContent>
          ))}
        </Tabs>
        <Audit />
      </RequireUnlock>
    </div>
  )
}

type Draft = Record<string, SettingValue>

function SettingsFileEditor({ file }: { file: SettingsFileId }) {
  const { t } = useTranslation('admin')
  const page = useSettingsFile(file)
  if (page.isPending) return <Skeleton className="h-96 rounded-xl" />
  if (page.isError) return <ErrorState error={page.error} title={t('loadFailed')} onRetry={() => void page.refetch()} className="rounded-xl border" />
  return (
    <>
      <Editor key={page.data.status.revision} file={file} page={page.data} />
      <Backups file={file} revision={page.data.status.revision} />
    </>
  )
}

function groupOf(setting: string): string {
  return setting.includes('.') ? setting.split('.')[0]! : 'prompts'
}

function Editor({ file, page }: { file: SettingsFileId; page: SettingsFilePage }) {
  const { t } = useTranslation('admin')
  const [draft, setDraft] = useState<Draft>({})
  /** Bumped by discard so every field, typed text included, starts again from the file. */
  const [generation, setGeneration] = useState(0)
  const [query, setQuery] = useState('')
  const [edit, setEdit] = useState<SettingsEdit | null>(null)
  const preview = usePreviewChange(file)
  const save = useSaveChange(file)
  const changed = Object.keys(draft)
  const needle = query.trim().toLowerCase()
  const visible = page.settings.filter((item) => !needle || item.setting.includes(needle) || t(`setting.${item.setting.replaceAll('.', '_')}`).toLowerCase().includes(needle))
  const groups = [...new Set(visible.map((item) => groupOf(item.setting)))]

  const set = (setting: string, value: SettingValue, original: unknown) => {
    setEdit(null)
    setDraft((current) => {
      const next = { ...current }
      if (JSON.stringify(value) === JSON.stringify(original)) delete next[setting]
      else next[setting] = value
      return next
    })
  }

  const discard = () => {
    setDraft({})
    setEdit(null)
    setGeneration((value) => value + 1)
  }

  const runPreview = () =>
    preview.mutate({ revision: page.status.revision, changes: draft }, { onSuccess: setEdit, onError: (error) => toast.error(t('previewFailed', { reason: error.message })) })

  const runSave = () =>
    save.mutate(
      { revision: page.status.revision, changes: draft },
      {
        onSuccess: () => toast.success(t('saved'), { description: t('restartNeeded') }),
        onError: (error) => {
          if (isApiError(error, 'conflict')) toast.error(t('conflict'))
          else toast.error(t('saveRefused'), { description: error.message })
        },
      },
    )

  return (
    <div className="space-y-4">
      <FileStatus page={page} />
      <div className="sticky top-(--topbar-height) z-10 -mx-1 flex flex-wrap items-center justify-between gap-2 bg-background/95 px-1 py-2 backdrop-blur">
        <div className="relative w-full max-w-xs">
          <Search aria-hidden className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('search')} aria-label={t('search')} className="h-8 pl-8" />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="tabular text-xs text-muted-foreground" aria-live="polite">
            {t('changedCount', { count: changed.length })}
          </span>
          <Button type="button" variant="ghost" size="sm" disabled={changed.length === 0} onClick={discard}>
            {t('discard')}
          </Button>
          <Button type="button" variant="outline" size="sm" disabled={changed.length === 0 || preview.isPending} onClick={runPreview}>
            {t('preview')}
          </Button>
          <Button type="button" size="sm" disabled={changed.length === 0 || save.isPending} onClick={runSave}>
            <Save aria-hidden />
            {t('save')}
          </Button>
        </div>
      </div>
      {edit && <EditPreview edit={edit} baseRevision={page.status.revision} />}
      {groups.map((group) => (
        <Panel key={group} title={t(`group.${group}`)}>
          <div className="grid gap-x-6 gap-y-4 md:grid-cols-2">
            {visible
              .filter((item) => groupOf(item.setting) === group)
              .map((item) => (
                <SettingField
                  key={`${item.setting}:${generation}`}
                  setting={item.setting}
                  value={item.setting in draft ? draft[item.setting] : (item.value as SettingValue)}
                  choices={item.choices}
                  modified={item.setting in draft}
                  onChange={(value) => set(item.setting, value, item.value)}
                />
              ))}
          </div>
        </Panel>
      ))}
      {file === 'appsetting' && <Locked locked={page.locked} />}
    </div>
  )
}

function FileStatus({ page }: { page: SettingsFilePage }) {
  const { t } = useTranslation('admin')
  const locale = useLocale()
  const { status } = page
  return (
    <div className={cn('flex flex-wrap items-start gap-2.5 rounded-lg border px-3 py-2 text-sm', status.restart_required ? 'border-gold/40 bg-gold-soft' : 'bg-card')} aria-live="polite">
      {status.restart_required ? <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-gold" /> : <ShieldCheck aria-hidden className="mt-0.5 size-4 shrink-0 text-jade" />}
      <div className="min-w-0 space-y-0.5">
        <p className="font-medium">{t(status.restart_required ? 'restartRequired' : 'inSync')}</p>
        <p className="text-xs text-muted-foreground">
          <span className="tabular font-mono">{t('revisions', { file: status.revision.slice(0, 12), running: status.running_revision?.slice(0, 12) ?? '—' })}</span> ·{' '}
          {formatDateTime(locale, status.modified_at)} · {t('applyNote')}
        </p>
      </div>
    </div>
  )
}

/**
 * One editable setting. Numbers and lists keep the text as typed, so a half-typed number, a space inside a keyword or
 * a new empty line stays on screen; the draft gets the parsed value.
 */
function SettingField(props: { setting: string; value: SettingValue | undefined; choices: string[]; modified: boolean; onChange: (value: SettingValue) => void }) {
  const { t } = useTranslation('admin')
  const { setting, value, choices, modified, onChange } = props
  const id = `setting-${setting}`
  const label = t(`setting.${setting.replaceAll('.', '_')}`)
  const control = (() => {
    if (choices.length > 0) {
      return (
        <Select value={String(value ?? '')} onValueChange={(next) => onChange(next)}>
          <SelectTrigger id={id} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {choices.map((choice) => (
              <SelectItem key={choice} value={choice}>
                {choice}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )
    }
    if (typeof value === 'boolean') return <Switch id={id} checked={value} onCheckedChange={onChange} />
    if (typeof value === 'number') return <Input id={id} inputMode="decimal" defaultValue={String(value)} onChange={(event) => onChange(event.target.value.trim() === '' ? Number.NaN : Number(event.target.value))} />
    if (Array.isArray(value)) {
      return <Textarea id={id} rows={4} defaultValue={value.join('\n')} onChange={(event) => onChange(event.target.value.split('\n').map((line) => line.trim()).filter(Boolean))} />
    }
    const multiline = typeof value === 'string' && (value.includes('\n') || value.length > 80)
    return multiline ? (
      <Textarea id={id} rows={10} className="font-mono text-xs" value={value ?? ''} onChange={(event) => onChange(event.target.value)} />
    ) : (
      <Input id={id} value={value ?? ''} onChange={(event) => onChange(event.target.value)} />
    )
  })()
  return (
    <div className={cn('min-w-0 space-y-1.5', modified && 'rounded-lg ring-2 ring-primary/40 ring-offset-4 ring-offset-card')}>
      <div className="flex items-center justify-between gap-2">
        <Label htmlFor={id}>{label}</Label>
        {modified && <span className="text-xs text-primary">{t('modified')}</span>}
      </div>
      {control}
      <p className="truncate font-mono text-[0.6875rem] text-faint">{setting}</p>
    </div>
  )
}

function EditPreview({ edit, baseRevision }: { edit: SettingsEdit; baseRevision: string }) {
  const { t } = useTranslation('admin')
  return (
    <Panel title={t('previewTitle', { count: edit.changed.length })}>
      {edit.base_revision !== baseRevision && <p className="mb-2 text-sm text-gold">{t('previewStale')}</p>}
      {edit.problems.length > 0 ? (
        <ul className="list-disc space-y-1 pl-5 text-sm text-destructive" role="alert">
          {edit.problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-jade">{t('previewValid')}</p>
      )}
      <pre className="mt-3 max-h-80 overflow-auto rounded-lg bg-muted/60 p-3 font-mono text-xs leading-relaxed">
        {edit.diff.map((line, index) => (
          <span key={index} className={cn('block', line.startsWith('+') && 'text-jade', line.startsWith('-') && 'text-destructive')}>
            {line}
          </span>
        ))}
      </pre>
    </Panel>
  )
}

function Locked({ locked }: { locked: SettingsFilePage['locked'] }) {
  const { t } = useTranslation('admin')
  return (
    <Panel
      title={
        <>
          <LockKeyhole aria-hidden className="size-4 text-muted-foreground" />
          {t('lockedTitle')}
        </>
      }
    >
      <p className="mb-3 text-xs text-muted-foreground">{t('lockedNote')}</p>
      <dl className="grid gap-x-6 text-sm sm:grid-cols-2">
        {Object.entries(locked).map(([setting, value]) => (
          <div key={setting} className="flex justify-between gap-3 border-b py-1.5">
            <dt className="truncate font-mono text-xs text-muted-foreground">{setting}</dt>
            <dd className="tabular">{String(value)}</dd>
          </div>
        ))}
      </dl>
    </Panel>
  )
}

function Backups({ file, revision }: { file: SettingsFileId; revision: string }) {
  const { t } = useTranslation('admin')
  const locale = useLocale()
  const backups = useSettingsBackups(file)
  const preview = usePreviewRestore(file)
  const restore = useRestore(file)
  const [shown, setShown] = useState<{ backupId: string; edit: SettingsEdit } | null>(null)

  const show = (backupId: string) => {
    setShown(null)
    preview.mutate({ backupId, revision }, { onSuccess: (edit) => setShown({ backupId, edit }) })
  }
  const put = (backupId: string, previewed: string) =>
    restore.mutate(
      { backupId, revision: previewed },
      {
        onSuccess: () => (setShown(null), toast.success(t('restored'), { description: t('restartNeeded') })),
        onError: (error) => toast.error(isApiError(error, 'conflict') ? t('conflict') : t('saveRefused'), { description: error.message }),
      },
    )

  return (
    <Panel
      title={
        <>
          <History aria-hidden className="size-4 text-muted-foreground" />
          {t('backupsTitle')}
        </>
      }
      flush
    >
      {backups.data?.length === 0 && <p className="px-4 py-3 text-sm text-muted-foreground">{t('noBackups')}</p>}
      <ul className="max-h-96 divide-y overflow-y-auto">
        {backups.data?.map((backup) => (
          <li key={backup.backup_id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-2 text-sm">
            <span className="tabular">
              {formatDateTime(locale, backup.created_at)} <span className="font-mono text-xs text-muted-foreground">{backup.revision.slice(0, 12)}</span>
            </span>
            <span className="flex gap-2">
              <Button type="button" size="xs" variant="outline" onClick={() => show(backup.backup_id)} disabled={preview.isPending}>
                {t('previewRestore')}
              </Button>
              {shown?.backupId === backup.backup_id && shown.edit.problems.length === 0 && shown.edit.base_revision === revision && (
                <Button type="button" size="xs" onClick={() => put(backup.backup_id, shown.edit.base_revision)} disabled={restore.isPending}>
                  <RotateCcw aria-hidden />
                  {t('restore')}
                </Button>
              )}
            </span>
          </li>
        ))}
      </ul>
      {preview.isError && (
        <p role="alert" className="border-t px-4 py-3 text-sm text-destructive">
          {t('previewFailed', { reason: preview.error.message })}
        </p>
      )}
      {shown && (
        <div className="border-t p-4">
          <EditPreview edit={shown.edit} baseRevision={revision} />
        </div>
      )}
    </Panel>
  )
}

function Audit() {
  const { t } = useTranslation('admin')
  const locale = useLocale()
  const audit = useSettingsAudit()
  if (audit.isError) {
    return (
      <Panel title={t('auditTitle')}>
        <ErrorState error={audit.error} title={t('auditFailed')} onRetry={() => void audit.refetch()} />
      </Panel>
    )
  }
  if (!audit.data || audit.data.length === 0) return null
  return (
    <Panel title={t('auditTitle')}>
      <ul className="space-y-1 text-xs text-muted-foreground">
        {audit.data.map((entry) => (
          <li key={`${entry.recorded_at}-${entry.to_revision}`} className="tabular">
            {formatDateTime(locale, entry.recorded_at)} · {t(`action.${entry.action}`)} · {t(`file.${entry.file}`)} · {entry.from_revision.slice(0, 8)} → {entry.to_revision.slice(0, 8)} ·{' '}
            {entry.settings.join(', ') || '—'}
          </li>
        ))}
      </ul>
    </Panel>
  )
}
