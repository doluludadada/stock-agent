import { useQueryClient } from '@tanstack/react-query'
import { CircleCheck, CircleDot, FileWarning, Info, LoaderCircle, RotateCcw, Save, TriangleAlert, X } from 'lucide-react'
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react'
import { useLocale, useTranslation } from '@/i18n'
import { isApiError } from '@/shared/api'
import { formatMonthDayTime } from '@/shared/lib/format'
import { useDebouncedValue } from '@/shared/lib/use-debounced-value'
import { cn } from '@/shared/lib/utils'
import { Button } from '@/shared/ui/button'
import { ConfirmDialog } from '@/shared/ui/confirm-dialog'
import { ErrorState } from '@/shared/ui/error-state'
import { Panel } from '@/shared/ui/panel'
import { Skeleton } from '@/shared/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/shared/ui/tabs'
import { settingsKeys, useSaveSettings, useSettingsAudit, useSettingsCheck, useSettingsText, wasWrittenHere } from './api'
import { ChangeSummary, LineChanges, ProblemList, type Reveal } from './CheckDetails'
import { drafts, PAGE_LOADED_AT, useDraft } from './drafts'
import { FORM_FILE } from './form'
import { History } from './History'
import { checkOf, diskStateOf, linesAdded, locatedIn, reasonOf, refusalOf, type Check, type FileStatus, type SettingsEdit, type SettingsOverview, type SettingsProblem } from './model'
import { ReviewDialog, type DialogRefusal } from './ReviewDialog'
import { SettingsForm } from './SettingsForm'
import { YamlEditor, type YamlEditorHandle } from './YamlEditor'

/** The pause after the last key before the server checks the text. */
const CHECK_DELAY_MS = 450

/** A request to put the caret on a problem; `at` tells a second request for the same place from the first. */
export interface RevealRequest {
  line: number
  column: number
  at: number
}

/** appsetting.yaml opens on its form; its text, and every other file's, is the Advanced (YAML) view. */
type View = 'form' | 'yaml'

/**
 * What the last save or restore did, until the text changes again. A refusal names the text it is about: the draft's,
 * or null for a restore, whose problems sit in the version being restored and not in the editor.
 */
type Outcome =
  | { kind: 'saved'; edit: SettingsEdit; at: string; version: string | null }
  | { kind: 'refused'; problems: SettingsProblem[]; detail: string; text: string | null }
  | { kind: 'reloaded' }
  | { kind: 'restoreMoved' }

interface FileWorkspaceProps {
  status: FileStatus
  overview: SettingsOverview
  /** The signed-in administrator's user id: drafts are theirs, and the history calls them "you". */
  owner: string
  /** A problem the page asked to show, from the banner above the file. */
  reveal: RevealRequest | null
  throttledUntil: number | null
  onThrottled: (until: number) => void
}

/** Restored-draft notices already read, so switching files does not repeat them. */
const acknowledged = new Set<string>()

/**
 * One settings file: its form or its text in the editor, the server's check as the administrator edits, the save with
 * its review and password, what the save did, a newer file on disk, and the file's history. The form and the editor
 * are two views of one unsaved text, so a change in either shows in the other and saves the same way.
 */
export function FileWorkspace({ status, overview, owner, reveal, throttledUntil, onThrottled }: FileWorkspaceProps) {
  const { t } = useTranslation('admin')
  const locale = useLocale()
  const client = useQueryClient()
  const file = status.file
  const fileName = t(`file.${file}`)
  const shown = useSettingsText(file, status.revision)
  const draft = useDraft(file, owner)
  const audit = useSettingsAudit()
  const save = useSaveSettings(file)
  const editor = useRef<YamlEditorHandle>(null)
  const keysHint = useId()
  const [reviewing, setReviewing] = useState(false)
  const [discarding, setDiscarding] = useState(false)
  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const [updatedAt, setUpdatedAt] = useState<string | null>(null)
  const [seenRevision, setSeenRevision] = useState(status.revision)
  const [view, setView] = useState<View>('form')
  const showing: View = file === FORM_FILE ? view : 'yaml'
  const [target, setTarget] = useState<RevealRequest | null>(null)
  const [seenReveal, setSeenReveal] = useState<RevealRequest | null>(null)

  const disk = diskStateOf(overview, status)
  const conflict = draft !== null && draft.base.revision !== status.revision
  const debounced = useDebouncedValue(draft?.text ?? null, CHECK_DELAY_MS)
  const check = useSettingsCheck(file, draft?.base.revision ?? '', debounced ?? '', draft !== null && !conflict && debounced !== null)
  const settled = draft !== null && debounced === draft.text && !check.isPlaceholderData
  const state: Check | null =
    draft === null || conflict
      ? null
      : settled && check.data
        ? checkOf(check.data)
        : settled && check.isError && !isApiError(check.error, 'conflict')
          ? { kind: 'failed', error: check.error }
          : { kind: 'checking' }
  const refused = outcome?.kind === 'refused' && outcome.text === (draft?.text ?? null) ? outcome : null
  const restoredKey = draft ? `${owner}:${file}:${draft.editedAt}` : null
  const [restored, setRestored] = useState(() => (draft && draft.editedAt < PAGE_LOADED_AT && restoredKey && !acknowledged.has(restoredKey) ? draft.editedAt : null))

  useEffect(() => {
    if (isApiError(check.error, 'conflict')) void client.invalidateQueries({ queryKey: settingsKeys.overview })
  }, [check.error, client])

  if (seenRevision !== status.revision) {
    setSeenRevision(status.revision)
    if (draft === null && !wasWrittenHere(status.revision)) setUpdatedAt(status.modified_at)
  }

  /** Puts the caret on a place in the text, opening the YAML view first when the form is showing. */
  const revealAt = (line: number, column: number) => {
    setView('yaml')
    setTarget({ line, column, at: Date.now() })
  }

  if (seenReveal !== reveal) {
    setSeenReveal(reveal)
    if (reveal) {
      setView('yaml')
      setTarget(reveal)
    }
  }

  // The caret moves once the YAML view shows, so the editor can scroll it into view.
  const revealed = useRef(0)
  useEffect(() => {
    if (!target || showing !== 'yaml' || revealed.current === target.at) return
    revealed.current = target.at
    editor.current?.reveal(target.line, target.column)
  }, [target, showing])

  // Another administrator's save brings a revision this page did not write: its audit entry and backup are new too.
  const readRevision = useRef(status.revision)
  useEffect(() => {
    if (readRevision.current === status.revision) return
    readRevision.current = status.revision
    void client.invalidateQueries({ queryKey: settingsKeys.audit })
    void client.invalidateQueries({ queryKey: settingsKeys.backups(file) })
  }, [status.revision, client, file])

  const editing = draft !== null
  const refusal = disk.kind === 'refused' ? disk.refusal : null
  const problems = useMemo(() => {
    if (refused?.text) return locatedIn(refused.problems, file)
    if (editing) return locatedIn(check.data?.problems ?? [], file)
    return refusal ? locatedIn(refusal.problems, file) : []
  }, [refused, editing, check.data, refusal, file])

  const edit = (text: string) => {
    if (!shown.data) return
    if (restoredKey) acknowledged.add(restoredKey)
    setRestored(null)
    setUpdatedAt(null)
    if (outcome?.kind !== 'refused') setOutcome(null)
    drafts.put(file, { ...draft, owner, base: draft?.base ?? shown.data, text, editedAt: new Date().toISOString() })
  }

  const changedLines = useMemo(() => (editing ? linesAdded(check.data?.diff ?? []) : []), [editing, check.data])

  /** The save button and Ctrl+S: the review when the text is ready, the first problem when it has one. */
  const openReview = () => {
    if (state?.kind === 'ready') setReviewing(true)
    if (state?.kind === 'problems' && problems[0]) revealAt(problems[0].line, problems[0].column)
  }

  const confirmSave = async (password: string): Promise<DialogRefusal | null> => {
    if (!draft) return null
    try {
      const saved = await save.mutateAsync({ revision: draft.base.revision, text: draft.text, password }, { onSuccess: () => drafts.discard(file) })
      setReviewing(false)
      setOutcome({ kind: 'saved', edit: saved, at: new Date().toISOString(), version: null })
      return null
    } catch (error) {
      const refusal = refusalOf(error)
      if (refusal.kind === 'refused') {
        setReviewing(false)
        setOutcome({ kind: 'refused', problems: refusal.problems, detail: refusal.detail, text: draft.text })
        return null
      }
      if (refusal.kind === 'conflict') {
        setReviewing(false)
        await client.refetchQueries({ queryKey: settingsKeys.overview })
        const now = client.getQueryData<SettingsOverview>(settingsKeys.overview)?.files.find((item) => item.file === file)
        setOutcome(now?.revision === draft.base.revision ? { kind: 'reloaded' } : null)
        return null
      }
      return refusal
    }
  }

  const keepMine = () => {
    if (!draft || shown.data?.revision !== status.revision) return
    drafts.put(file, { ...draft, base: shown.data, rebased: true, editedAt: new Date().toISOString() })
  }

  const mod = /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘' : 'Ctrl'
  const notLoaded = shown.isError ? (
    <ErrorState error={shown.error} title={t('loadFailed')} onRetry={() => void shown.refetch()} className="h-full" />
  ) : (
    <Skeleton className="h-full rounded-none" />
  )
  const yamlView = (
    <>
      {/* Below the side column's width the check sits under the editor, so the editor leaves room for its title. */}
      <div className="h-[max(18rem,58dvh)] md:h-[max(24rem,calc(100dvh-24rem))] xl:h-[max(26rem,calc(100dvh-21rem))]">
        {shown.data ? (
          <YamlEditor
            ref={editor}
            value={draft?.text ?? shown.data.text}
            onChange={edit}
            onSave={openReview}
            problems={problems}
            changedLines={changedLines}
            label={t('editor.label', { file: fileName })}
            describedBy={keysHint}
          />
        ) : (
          notLoaded
        )}
      </div>
      <p id={keysHint} className="hidden border-t px-4 py-2 text-xs text-pretty text-muted-foreground md:block">
        {t('editor.keys', { mod })}
      </p>
    </>
  )
  const lastSave = audit.data?.find((entry) => entry.file === file && entry.to_revision === status.revision)

  return (
    <div className="grid items-start gap-4 lg:gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(20rem,24rem)]">
      <section aria-label={fileName} className="min-w-0 overflow-clip rounded-2xl border bg-card shadow-card">
        <header className="sticky top-(--topbar-height) z-10 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b bg-card/95 px-3 py-2.5 backdrop-blur md:px-4">
          <div className="min-w-0 space-y-0.5">
            <FileState draft={draft !== null} conflict={conflict} disk={disk.kind} />
            <p className="tabular truncate text-xs text-muted-foreground" title={status.revision}>
              {t('facts.revision', { revision: status.revision.slice(0, 7) })} ·{' '}
              {!lastSave
                ? t('facts.edited', { time: formatMonthDayTime(locale, status.modified_at) })
                : lastSave.actor === owner
                  ? t('facts.savedByYou', { time: formatMonthDayTime(locale, lastSave.recorded_at) })
                  : t('facts.saved', { name: lastSave.actor_name ?? t('history.unknown'), time: formatMonthDayTime(locale, lastSave.recorded_at) })}
            </p>
          </div>
          <div className={cn('flex items-center gap-2', draft ? 'w-full sm:w-auto' : 'ml-auto')}>
            <span aria-live="polite" className="min-w-0">
              <CheckStatus state={state} onFirstProblem={() => problems[0] && revealAt(problems[0].line, problems[0].column)} />
            </span>
            {draft && (
              <Button type="button" variant="ghost" size="sm" onClick={() => setDiscarding(true)} className="ml-auto sm:ml-0">
                <RotateCcw aria-hidden />
                {t('discard')}
              </Button>
            )}
            <Button type="button" size="sm" onClick={openReview} disabled={state?.kind !== 'ready'}>
              <Save aria-hidden />
              {t('save')}
            </Button>
          </div>
        </header>

        {conflict && draft && (
          <Banner tone="warning" icon={FileWarning} title={t('conflict.title', { file: fileName })}>
            <p>{t('conflict.description', { time: formatMonthDayTime(locale, status.modified_at) })}</p>
            <div className="mt-2.5 flex flex-wrap gap-2">
              <Button type="button" size="sm" onClick={keepMine} disabled={shown.data?.revision !== status.revision}>
                {t('conflict.keep')}
              </Button>
              <Button type="button" variant="outline" size="sm" onClick={() => setDiscarding(true)} className="bg-card">
                {t('conflict.load')}
              </Button>
            </div>
          </Banner>
        )}
        {outcome?.kind === 'saved' && !draft && (
          <Banner
            tone="success"
            icon={CircleCheck}
            onDismiss={() => setOutcome(null)}
            title={
              !outcome.edit.applied
                ? t('outcome.pending', { time: formatMonthDayTime(locale, outcome.at) })
                : outcome.version
                  ? t('outcome.restored', { version: outcome.version, time: formatMonthDayTime(locale, outcome.at) })
                  : t('outcome.saved', { time: formatMonthDayTime(locale, outcome.at) })
            }
          >
            {overview.draining > 0 && <p>{t('outcome.draining', { count: overview.draining })}</p>}
          </Banner>
        )}
        {refused && <Banner tone="danger" icon={TriangleAlert} title={t('outcome.refused')} />}
        {outcome?.kind === 'reloaded' && <Banner tone="warning" icon={Info} onDismiss={() => setOutcome(null)} title={t('outcome.reloaded')} />}
        {outcome?.kind === 'restoreMoved' && <Banner tone="warning" icon={Info} onDismiss={() => setOutcome(null)} title={t('outcome.restoreMoved')} />}
        {restored && draft && (
          <Banner
            tone="info"
            icon={Info}
            onDismiss={() => {
              if (restoredKey) acknowledged.add(restoredKey)
              setRestored(null)
            }}
            title={t('notice.restored', { time: formatMonthDayTime(locale, restored) })}
          />
        )}
        {updatedAt && !draft && <Banner tone="info" icon={Info} onDismiss={() => setUpdatedAt(null)} title={t('notice.updated', { time: formatMonthDayTime(locale, updatedAt) })} />}

        {file === FORM_FILE ? (
          <Tabs value={showing} onValueChange={(next) => setView(next === 'form' ? 'form' : 'yaml')} className="gap-0">
            <div className="border-b px-2 md:px-3">
              <TabsList variant="line" aria-label={t('view.label', { file: fileName })}>
                <TabsTrigger value="form" className="px-2.5">
                  {t('view.form')}
                </TabsTrigger>
                <TabsTrigger value="yaml" className="px-2.5">
                  {t('view.yaml')}
                </TabsTrigger>
              </TabsList>
            </div>
            <TabsContent value="form">
              {shown.data ? (
                <SettingsForm text={draft?.text ?? shown.data.text} onText={edit} problems={problems} onOpenYaml={() => setView('yaml')} />
              ) : (
                <div className="h-96">{notLoaded}</div>
              )}
            </TabsContent>
            {/* Kept mounted, so its undo history and scroll survive a visit to the form and a reveal finds the editor. */}
            <TabsContent value="yaml" forceMount className="data-[state=inactive]:hidden">
              {yamlView}
            </TabsContent>
          </Tabs>
        ) : (
          yamlView
        )}
      </section>

      <div className="min-w-0 space-y-4 lg:space-y-5">
        <CheckPanel
          state={state}
          conflict={conflict}
          refused={refused}
          rebased={draft?.rebased === true}
          stale={draft !== null && check.isPlaceholderData}
          onReveal={revealAt}
          onRetry={() => void check.refetch()}
          file={file}
        />
        <History
          file={file}
          revision={status.revision}
          me={owner}
          blocked={draft ? t('history.restoreBlocked', { file: fileName }) : null}
          throttledUntil={throttledUntil}
          onThrottled={onThrottled}
          onRestored={(restoredEdit, version) => {
            setOutcome({ kind: 'saved', edit: restoredEdit, at: new Date().toISOString(), version })
          }}
          onRefused={(refusal) => {
            if (refusal.kind === 'conflict') {
              void client.invalidateQueries({ queryKey: settingsKeys.overview })
              setOutcome({ kind: 'restoreMoved' })
            }
            if (refusal.kind === 'refused') setOutcome({ kind: 'refused', problems: refusal.problems, detail: refusal.detail, text: null })
          }}
        />
      </div>

      {state?.kind === 'ready' && (
        <ReviewDialog
          open={reviewing}
          onOpenChange={setReviewing}
          title={t('review.title', { file: fileName })}
          description={t('review.description')}
          confirmLabel={t('review.confirm')}
          review={{ kind: 'ready', edit: state.edit }}
          onConfirm={confirmSave}
          throttledUntil={throttledUntil}
          onThrottled={onThrottled}
        />
      )}
      <ConfirmDialog
        open={discarding}
        onOpenChange={setDiscarding}
        title={t('discardTitle')}
        description={t('discardDescription', { file: fileName })}
        cancel={t('leave.stay')}
        confirm={conflict ? t('conflict.load') : t('discard')}
        onConfirm={() => {
          drafts.discard(file)
          setOutcome(null)
        }}
        destructive
      />
    </div>
  )
}

/** The file's state in one line: what the reader should know first. */
function FileState({ draft, conflict, disk }: { draft: boolean; conflict: boolean; disk: 'running' | 'loading' | 'refused' }) {
  const { t } = useTranslation('admin')
  const [key, tone] = conflict
    ? (['conflict', 'text-gold'] as const)
    : draft
      ? (['unsaved', 'text-gold'] as const)
      : disk === 'refused'
        ? (['refused', 'text-destructive'] as const)
        : disk === 'loading'
          ? (['loading', 'text-muted-foreground'] as const)
          : (['running', 'text-brand'] as const)
  const Icon = key === 'running' ? CircleCheck : key === 'loading' ? LoaderCircle : key === 'refused' ? TriangleAlert : CircleDot
  return (
    <p className="flex items-center gap-1.5 text-sm font-medium" aria-live="polite">
      <Icon aria-hidden className={cn('size-4 shrink-0', tone, key === 'loading' && 'animate-spin')} />
      <span className="truncate">{t(`state.${key}`)}</span>
    </p>
  )
}

/** The check in a word beside the save button: why it is off, or that it is ready. */
function CheckStatus({ state, onFirstProblem }: { state: Check | null; onFirstProblem: () => void }) {
  const { t } = useTranslation('admin')
  if (!state) return null
  if (state.kind === 'checking') {
    return (
      <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <LoaderCircle aria-hidden className="size-3.5 animate-spin" />
        {t('status.checking')}
      </span>
    )
  }
  if (state.kind === 'problems') {
    return (
      <button type="button" onClick={onFirstProblem} className="tabular min-h-11 rounded-md px-1 text-xs font-medium text-destructive underline-offset-2 hover:underline md:min-h-7">
        {t('status.problems', { count: state.edit.problems.length })}
      </button>
    )
  }
  return (
    <span className={cn('text-xs', state.kind === 'ready' ? 'text-brand' : 'text-muted-foreground')}>
      {t(`status.${state.kind}`)}
    </span>
  )
}

interface CheckPanelProps {
  state: Check | null
  conflict: boolean
  refused: Extract<Outcome, { kind: 'refused' }> | null
  rebased: boolean
  stale: boolean
  file: FileStatus['file']
  onReveal: Reveal
  onRetry: () => void
}

/** The server's check of the text: its problems, or what a save would change; how a save works while nothing changed. */
function CheckPanel({ state, conflict, refused, rebased, stale, file, onReveal, onRetry }: CheckPanelProps) {
  const { t } = useTranslation('admin')
  const body = (() => {
    if (refused) {
      return (
        <div className="space-y-3">
          <p className="text-sm text-pretty">{refused.problems.length > 0 ? t('check.problems') : refused.detail}</p>
          <ProblemList problems={refused.problems} file={file} onReveal={refused.text === null ? undefined : onReveal} />
        </div>
      )
    }
    if (conflict) return <p className="text-sm text-pretty text-muted-foreground">{t('check.paused')}</p>
    if (!state) return <HowSavingWorks />
    switch (state.kind) {
      case 'checking':
        return (
          <p className="flex items-center gap-2 text-sm text-muted-foreground" aria-live="polite">
            <LoaderCircle aria-hidden className="size-4 animate-spin" />
            {t('check.checking')}
          </p>
        )
      case 'failed':
        return (
          <div className="space-y-2">
            <p className="text-sm text-destructive" role="alert">
              {t('check.failed', { reason: reasonOf(state.error, t) })}
            </p>
            <Button type="button" variant="outline" size="sm" onClick={onRetry}>
              {t('check.retry')}
            </Button>
          </div>
        )
      case 'problems':
        return (
          <div className="space-y-3">
            <p className="text-sm text-pretty">{t('check.problems')}</p>
            <ProblemList problems={state.edit.problems} file={file} onReveal={onReveal} />
            <LineChanges diff={state.edit.diff} onRevealLine={(line) => onReveal(line, 1)} />
          </div>
        )
      case 'ready':
        return (
          <div className="space-y-3">
            <p className="flex items-center gap-1.5 text-sm text-brand">
              <CircleCheck aria-hidden className="size-4 shrink-0" />
              {t('check.ready')}
            </p>
            {rebased && <p className="rounded-lg border border-gold/35 bg-gold-soft px-3 py-2 text-sm text-pretty">{t('check.rebased')}</p>}
            <ChangeSummary edit={state.edit} />
            <LineChanges diff={state.edit.diff} defaultOpen={rebased} onRevealLine={(line) => onReveal(line, 1)} />
          </div>
        )
    }
  })()
  return (
    <Panel title={t('check.title')} aside={stale ? <span className="text-xs text-muted-foreground">{t('check.stale')}</span> : undefined} className={cn(stale && '[&_ol]:opacity-60')}>
      {body}
    </Panel>
  )
}

function HowSavingWorks() {
  const { t } = useTranslation('admin')
  const items = [t('help.check'), t('help.password'), t('help.apply'), t('help.disk'), t('help.history')]
  return (
    <div className="space-y-3">
      <p className="text-sm text-pretty text-muted-foreground">{t('check.clean')}</p>
      <div>
        <p className="eyebrow mb-1.5">{t('help.title')}</p>
        <ul className="space-y-1.5 text-sm text-pretty">
          {items.map((item) => (
            <li key={item} className="flex gap-2">
              <span aria-hidden className="mt-2 size-1 shrink-0 rounded-full bg-muted-foreground" />
              {item}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

const BANNER_TONES = {
  success: 'border-brand/25 bg-brand-soft [&_svg.banner-icon]:text-brand',
  info: 'bg-muted [&_svg.banner-icon]:text-muted-foreground',
  warning: 'border-gold/35 bg-gold-soft [&_svg.banner-icon]:text-gold',
  danger: 'border-destructive/30 bg-danger-soft [&_svg.banner-icon]:text-destructive',
} as const

/** A line about the file under the toolbar: what the last save did, a newer file on disk, a restored draft. */
function Banner({ tone, icon: Icon, title, children, onDismiss }: { tone: keyof typeof BANNER_TONES; icon: typeof Info; title: string; children?: ReactNode; onDismiss?: () => void }) {
  const { t } = useTranslation('admin')
  return (
    <div role={tone === 'danger' ? 'alert' : 'status'} className={cn('flex items-start gap-2.5 border-b px-3 py-2.5 text-sm md:px-4', BANNER_TONES[tone])}>
      <Icon aria-hidden className="banner-icon mt-0.5 size-4 shrink-0" />
      <div className="min-w-0 flex-1 space-y-0.5 text-pretty">
        <p className="font-medium">{title}</p>
        {children}
      </div>
      {onDismiss && (
        <Button type="button" variant="ghost" size="icon-xs" onClick={onDismiss} aria-label={t('outcome.dismiss')} className="-my-1 -mr-1">
          <X aria-hidden />
        </Button>
      )}
    </div>
  )
}
