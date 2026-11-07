import { Search, TriangleAlert } from 'lucide-react'
import { memo, useCallback, useEffect, useId, useMemo, useState, type ReactNode } from 'react'
import { useBlocker } from 'react-router'
import { toast } from 'sonner'
import { useTranslation } from '@/i18n'
import { cn } from '@/shared/lib/utils'
import { Button } from '@/shared/ui/button'
import { Checkbox } from '@/shared/ui/checkbox'
import { ConfirmDialog } from '@/shared/ui/confirm-dialog'
import { ErrorState } from '@/shared/ui/error-state'
import { Input } from '@/shared/ui/input'
import { Label } from '@/shared/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/ui/select'
import { Skeleton } from '@/shared/ui/skeleton'
import { Switch } from '@/shared/ui/switch'
import { Textarea } from '@/shared/ui/textarea'
import { useSaveSettings, useSettingsForm } from './api'
import { changesOf, inputOf, isLongText, problemsAt, problemsElsewhere, sectionsOf, type Input as FieldInput, type SettingField } from './form'
import { problemMessage, refusalOf, type SettingsProblem } from './model'
import { PasswordDialog, type DialogRefusal } from './PasswordDialog'

/** Every setting of the settings files as a form; a save runs on the new settings at once. */
export function SettingsForm() {
  const { t } = useTranslation('admin')
  const form = useSettingsForm()
  if (form.isPending) return <Skeleton className="h-[32rem] rounded-2xl" />
  if (form.isError) return <ErrorState error={form.error} title={t('loadFailed')} onRetry={() => void form.refetch()} className="rounded-2xl border bg-card" />
  return <FormBody fields={form.data} onStale={() => void form.refetch()} />
}

const rowId = (path: string) => `setting-${path}`

function FormBody({ fields, onStale }: { fields: SettingField[]; onStale: () => void }) {
  const { t } = useTranslation('admin')
  const save = useSaveSettings()
  const [inputs, setInputs] = useState<Record<string, FieldInput>>({})
  const [refused, setRefused] = useState<SettingsProblem[]>([])
  const [confirming, setConfirming] = useState(false)
  const [query, setQuery] = useState('')
  const { changes, problems } = useMemo(() => changesOf(fields, inputs), [fields, inputs])
  const shown = [...problems, ...refused]
  const changed = useMemo(() => new Set(changes.map((change) => change.path)), [changes])
  const dirty = changes.length > 0 || problems.length > 0
  const blocker = useLeaveGuard(dirty)

  useEffect(() => {
    const first = fields.find((field) => problemsAt(refused, field.path).length > 0)
    if (first) document.getElementById(rowId(first.path))?.scrollIntoView({ block: 'center' })
  }, [refused, fields])

  const edit = useCallback((path: string, input: FieldInput) => {
    setInputs((current) => ({ ...current, [path]: input }))
    setRefused((current) => current.filter((problem) => problemsAt([problem], path).length === 0))
  }, [])

  const confirm = async (password: string): Promise<DialogRefusal | null> => {
    try {
      await save.mutateAsync({ changes, password })
      setConfirming(false)
      setInputs({})
      setRefused([])
      toast.success(t('saved'))
      return null
    } catch (error) {
      const refusal = refusalOf(error)
      if (refusal.kind !== 'refused' && refusal.kind !== 'conflict') return refusal
      setConfirming(false)
      if (refusal.kind === 'conflict') onStale()
      const general = refusal.kind === 'conflict' ? t('conflict') : refusal.detail
      setRefused(refusal.kind === 'refused' && refusal.problems.length > 0 ? refusal.problems : [{ message: general, path: null }])
      return null
    }
  }

  const needle = query.trim().toLowerCase()
  const matches = (field: SettingField) =>
    !needle || [t(`form.field.${field.path}`), t(`form.help.${field.path}`), field.path].some((text) => text.toLowerCase().includes(needle))
  const sections = sectionsOf(fields.filter(matches))
  const elsewhere = problemsElsewhere(refused, fields)

  return (
    <div className="space-y-4">
      <div className="sticky top-(--topbar-height) z-10 -mx-1 flex flex-wrap items-center gap-2 bg-background/95 px-1 py-2 backdrop-blur">
        <div className="relative min-w-48 flex-1">
          <Search aria-hidden className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input type="search" value={query} onChange={(event) => setQuery(event.target.value)} aria-label={t('search.label')} placeholder={t('search.placeholder')} className="pl-9" />
        </div>
        {dirty && (
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              setInputs({})
              setRefused([])
            }}
          >
            {t('discard')}
          </Button>
        )}
        <Button type="button" onClick={() => setConfirming(true)} disabled={changes.length === 0 || problems.length > 0}>
          {t('save')}
        </Button>
      </div>

      {elsewhere.length > 0 && (
        <div role="alert" className="flex items-start gap-2.5 rounded-xl border border-destructive/30 bg-danger-soft px-4 py-3 text-sm">
          <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-destructive" />
          <ul className="space-y-1 text-pretty">
            {elsewhere.map((problem) => (
              <li key={problem.message}>{problemMessage(problem, t)}</li>
            ))}
          </ul>
        </div>
      )}

      {sections.length === 0 ? (
        <p className="py-12 text-center text-sm text-muted-foreground">{t('search.none', { query: query.trim() })}</p>
      ) : (
        <div className="divide-y rounded-2xl border bg-card shadow-card">
          {sections.map((section) => (
            <section key={section.id} aria-labelledby={`section-${section.id}`} className="px-4 py-5 md:px-6">
              <h2 id={`section-${section.id}`} className="text-title font-semibold">
                {t(`form.section.${section.id}`)}
              </h2>
              {section.groups.map((group) => (
                <div key={group.id ?? ''} className={cn(group.id && 'mt-4')}>
                  {group.id && <h3 className="eyebrow mt-2">{t(`form.group.${group.id}`)}</h3>}
                  <div className="divide-y divide-dashed">
                    {group.fields.map((field) => (
                      <SettingRow
                        key={field.path}
                        field={field}
                        input={inputs[field.path] ?? inputOf(field)}
                        changed={changed.has(field.path)}
                        problems={problemsAt(shown, field.path)}
                        onChange={edit}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </section>
          ))}
        </div>
      )}

      <PasswordDialog open={confirming} onOpenChange={setConfirming} onConfirm={confirm} />
      <ConfirmDialog
        open={blocker.state === 'blocked'}
        title={t('leave.title')}
        description={t('leave.description')}
        cancel={t('leave.stay')}
        confirm={t('leave.leave')}
        onCancel={() => blocker.reset?.()}
        onConfirm={() => blocker.proceed?.()}
      />
    </div>
  )
}

interface SettingRowProps {
  field: SettingField
  input: FieldInput
  changed: boolean
  problems: SettingsProblem[]
  onChange: (path: string, input: FieldInput) => void
}

/** One setting: its label and help, its control, and what is wrong with the value. */
function SettingRowView({ field, input, changed, problems, onChange }: SettingRowProps) {
  const { t } = useTranslation('admin')
  const id = useId()
  const [helpId, problemsId] = [`${id}-help`, `${id}-problems`]
  const wide = field.kind === 'lines' || field.kind === 'structure' || isLongText(field)
  const described: Described = {
    id,
    'aria-describedby': problems.length > 0 ? `${helpId} ${problemsId}` : helpId,
    'aria-invalid': problems.length > 0 || undefined,
  }
  const label = t(`form.field.${field.path}`)
  const labelled = !field.restart_only && field.kind !== 'choices'
  return (
    <div id={rowId(field.path)} className={cn('grid gap-x-6 gap-y-2 py-3.5', !wide && 'md:grid-cols-[minmax(0,1fr)_minmax(12rem,18rem)] md:items-start')}>
      <div className="min-w-0 space-y-1">
        <div className="flex items-center gap-2">
          {changed && (
            <>
              <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-gold" />
              <span className="sr-only">{t('form.changed')}</span>
            </>
          )}
          {labelled ? <Label htmlFor={id}>{label}</Label> : <p className="text-sm leading-none font-medium">{label}</p>}
        </div>
        <div id={helpId} className="space-y-1 text-xs text-pretty text-muted-foreground">
          <p>{t(`form.help.${field.path}`)}</p>
          {field.restart_only && <p>{t('form.restartOnly')}</p>}
        </div>
      </div>
      <div className="min-w-0 space-y-1.5">
        {field.restart_only ? (
          <p className="text-sm font-medium">{field.kind === 'choice' ? t(`form.option.${String(field.value)}`) : String(field.value)}</p>
        ) : (
          <Control field={field} input={input} label={label} described={described} onChange={(next) => onChange(field.path, next)} />
        )}
        {problems.length > 0 && (
          <ul id={problemsId} className="space-y-1">
            {problems.map((problem) => (
              <li key={`${problem.path}:${problem.message}`} className="text-xs text-pretty text-destructive">
                {problemMessage(problem, t)}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

/** A keystroke in one setting renders that row only, not the two hundred others. */
const SettingRow = memo(
  SettingRowView,
  (before, after) =>
    before.field === after.field &&
    before.input === after.input &&
    before.changed === after.changed &&
    before.onChange === after.onChange &&
    JSON.stringify(before.problems) === JSON.stringify(after.problems),
)

interface Described {
  id: string
  'aria-describedby': string
  'aria-invalid': true | undefined
}

interface ControlProps {
  field: SettingField
  input: FieldInput
  label: string
  described: Described
  onChange: (input: FieldInput) => void
}

/** The control the setting's kind gets: a switch, a select, checkboxes, a number, a text, a list or JSON. */
function Control({ field, input, label, described, onChange }: ControlProps) {
  const { t } = useTranslation('admin')
  const text = typeof input === 'string' ? input : ''
  switch (field.kind) {
    case 'switch':
      return <Switch {...described} checked={input === true} onCheckedChange={onChange} />
    case 'choice':
      return (
        <Select value={text} onValueChange={onChange}>
          <SelectTrigger {...described} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {field.options.map((option) => (
              <SelectItem key={option} value={option}>
                {t(`form.option.${option}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )
    case 'choices':
      return <Choices options={field.options} chosen={Array.isArray(input) ? input : []} label={label} described={described} onChange={onChange} />
    case 'integer':
    case 'number': {
      const min = field.minimum ?? field.exclusive_minimum ?? undefined
      const max = field.maximum ?? field.exclusive_maximum ?? undefined
      const step = field.kind === 'integer' ? 1 : 'any'
      return <Input {...described} type="number" inputMode={field.kind === 'integer' ? 'numeric' : 'decimal'} min={min} max={max} step={step} value={text} onChange={(event) => onChange(event.target.value)} className="tabular" />
    }
    case 'text':
      return isLongText(field) ? (
        <Textarea {...described} value={text} onChange={(event) => onChange(event.target.value)} className="max-h-96" />
      ) : (
        <Input {...described} value={text} onChange={(event) => onChange(event.target.value)} />
      )
    case 'lines':
      return (
        <Caption note={t('form.lines')}>
          <Textarea {...described} value={text} onChange={(event) => onChange(event.target.value)} spellCheck={false} className="max-h-80" />
        </Caption>
      )
    case 'structure':
      return (
        <Caption note={t('form.json')}>
          <Textarea {...described} value={text} onChange={(event) => onChange(event.target.value)} spellCheck={false} className="max-h-96 font-mono text-xs md:text-xs" />
        </Caption>
      )
  }
}

function Caption({ note, children }: { note: string; children: ReactNode }) {
  return (
    <div className="space-y-1">
      {children}
      <p className="text-xs text-muted-foreground">{note}</p>
    </div>
  )
}

interface ChoicesProps {
  options: readonly string[]
  chosen: string[]
  label: string
  described: Described
  onChange: (chosen: string[]) => void
}

/** A list of choices as checkboxes; a choice added goes last, so the order the file gives the others is kept. */
function Choices({ options, chosen, label, described, onChange }: ChoicesProps) {
  const { t } = useTranslation('admin')
  return (
    <fieldset id={described.id} aria-describedby={described['aria-describedby']} className="grid grid-cols-2 gap-2.5">
      <legend className="sr-only">{label}</legend>
      {options.map((option) => (
        <ChoiceItem
          key={option}
          label={t(`form.option.${option}`)}
          checked={chosen.includes(option)}
          onCheckedChange={(checked) => onChange(checked ? [...chosen, option] : chosen.filter((item) => item !== option))}
        />
      ))}
    </fieldset>
  )
}

function ChoiceItem({ label, checked, onCheckedChange }: { label: string; checked: boolean; onCheckedChange: (checked: boolean) => void }) {
  const id = useId()
  return (
    <div className="flex min-h-11 items-center gap-2.5 md:min-h-0">
      <Checkbox id={id} checked={checked} onCheckedChange={(state) => onCheckedChange(state === true)} />
      <Label htmlFor={id} className="font-normal">
        {label}
      </Label>
    </div>
  )
}

/**
 * Asks before leaving the page while a change is not saved. Closing or reloading the tab asks the browser's own
 * question.
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
