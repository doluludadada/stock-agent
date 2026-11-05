import { Server } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useBlocker, useSearchParams } from 'react-router'
import { useTranslation } from '@/i18n'
import { useSession } from '@/shared/api'
import { cn } from '@/shared/lib/utils'
import { ConfirmDialog } from '@/shared/ui/confirm-dialog'
import { ErrorState } from '@/shared/ui/error-state'
import { PageHeader } from '@/shared/ui/page-header'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { Skeleton } from '@/shared/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/shared/ui/tabs'
import { useSettingsOverview } from './api'
import { useUnsavedFiles } from './drafts'
import { FileWorkspace, type RevealRequest } from './FileWorkspace'
import { diskStateOf, isSettingsFileId, type SettingsFileId, type SettingsOverview } from './model'
import { ServerStatus } from './ServerStatus'

const DEFAULT_FILE: SettingsFileId = 'appsetting'

/** The administrator's settings files: edited as text, checked as the app starts, applied at once. */
export function AdminSettingsPage() {
  const { t } = useTranslation('admin')
  return (
    <div className="space-y-5">
      <PageHeader eyebrow={t('common:nav.section.admin')} title={t('title')} description={t('description')} />
      <RequireSignIn needs="edit_system_settings" layout="page" reason={t('signIn')}>
        <SettingsWorkspace />
      </RequireSignIn>
    </div>
  )
}

function SettingsWorkspace() {
  const { t } = useTranslation('admin')
  const current = useSession()
  const owner = current.status === 'signedIn' ? current.user.user_id : ''
  const overview = useSettingsOverview()
  const [params, setParams] = useSearchParams()
  const requested = params.get('file')
  const active = isSettingsFileId(requested) ? requested : DEFAULT_FILE
  const unsaved = useUnsavedFiles(owner)
  const [reveal, setReveal] = useState<(RevealRequest & { file: SettingsFileId }) | null>(null)
  const [throttledUntil, setThrottledUntil] = useState<number | null>(null)
  const blocker = useLeaveGuard(unsaved.length > 0)

  if (overview.isPending) return <Skeleton className="h-[32rem] rounded-2xl" />
  if (overview.isError) return <ErrorState error={overview.error} title={t('loadFailed')} onRetry={() => void overview.refetch()} className="rounded-2xl border bg-card" />

  const open = (file: SettingsFileId) => setParams(file === DEFAULT_FILE ? {} : { file }, { replace: true })
  const showProblem = (line: number, column: number) => setReveal({ file: active, line, column, at: Date.now() })
  const status = overview.data.files.find((item) => item.file === active)

  return (
    <div className="space-y-4">
      <ServerStatus overview={overview.data} active={active} onReveal={showProblem} />
      <Tabs value={active} onValueChange={(value) => isSettingsFileId(value) && open(value)} className="gap-4">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <TabsList aria-label={t('files')} className="w-full group-data-horizontal/tabs:h-[3.25rem] sm:w-fit md:group-data-horizontal/tabs:h-8">
            {overview.data.files.map((item) => (
              <TabsTrigger key={item.file} value={item.file} className="gap-2 px-3">
                <span className="font-mono text-[0.8125rem]">{item.file_name}</span>
                <span className="hidden text-xs font-normal text-muted-foreground lg:inline">{t(`fileRole.${item.file}`)}</span>
                <FileMark overview={overview.data} file={item.file} unsaved={unsaved.includes(item.file)} />
              </TabsTrigger>
            ))}
          </TabsList>
          <EnvironmentNote environment={overview.data.environment} />
        </div>
        {overview.data.files.map((item) => (
          <TabsContent key={item.file} value={item.file} className="min-w-0">
            {status && item.file === active && (
              <FileWorkspace
                status={status}
                overview={overview.data}
                owner={owner}
                reveal={reveal?.file === active ? reveal : null}
                throttledUntil={throttledUntil}
                onThrottled={setThrottledUntil}
              />
            )}
          </TabsContent>
        ))}
      </Tabs>
      <ConfirmDialog
        open={blocker.state === 'blocked'}
        title={t('leave.title')}
        description={t('leave.description', { files: unsaved.map((file) => t(`file.${file}`)).join(t('listSeparator')) })}
        cancel={t('leave.stay')}
        confirm={t('leave.leave')}
        onCancel={() => blocker.reset?.()}
        onConfirm={() => blocker.proceed?.()}
      />
    </div>
  )
}

/** A dot on a file's tab: unsaved text in it, or an edit on disk the server would not start with. */
function FileMark({ overview, file, unsaved }: { overview: SettingsOverview; file: SettingsFileId; unsaved: boolean }) {
  const { t } = useTranslation('admin')
  const status = overview.files.find((item) => item.file === file)
  const refused = status ? diskStateOf(overview, status).kind === 'refused' : false
  if (!unsaved && !refused) return null
  return (
    <>
      <span aria-hidden className={cn('order-first size-2 shrink-0 rounded-full', refused ? 'bg-destructive' : 'bg-gold')} />
      <span className="sr-only">, {refused ? t('refusedMark') : t('unsavedMark')}</span>
    </>
  )
}

function EnvironmentNote({ environment }: { environment: SettingsOverview['environment'] }) {
  const { t } = useTranslation('admin')
  return (
    <p className="flex items-center gap-1.5 text-xs text-muted-foreground" title={t('environmentNote', { environment })}>
      <Server aria-hidden className="size-3.5" />
      <span className="font-medium text-foreground">{t('environment', { environment })}</span>
      <span className="hidden md:inline">· {t('environmentNote', { environment })}</span>
    </p>
  )
}

/**
 * Asks before leaving the page while a file has unsaved text: the text stays in the tab either way, but the reader
 * should know it is not saved. Closing or reloading the tab asks the browser's own question.
 */
function useLeaveGuard(unsaved: boolean) {
  useEffect(() => {
    if (!unsaved) return
    const onBeforeUnload = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [unsaved])
  return useBlocker(({ currentLocation, nextLocation }) => unsaved && currentLocation.pathname !== nextLocation.pathname)
}
