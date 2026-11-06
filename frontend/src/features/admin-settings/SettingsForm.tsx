import { FileWarning } from 'lucide-react'
import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from '@/i18n'
import { isApiError } from '@/shared/api'
import { cn } from '@/shared/lib/utils'
import { Button } from '@/shared/ui/button'
import { Checkbox } from '@/shared/ui/checkbox'
import { ErrorState } from '@/shared/ui/error-state'
import { Input } from '@/shared/ui/input'
import { Label } from '@/shared/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/ui/select'
import { Skeleton } from '@/shared/ui/skeleton'
import { StateBlock } from '@/shared/ui/state-block'
import { Switch } from '@/shared/ui/switch'
import { useSettingsForm, useWriteSettingsForm } from './api'
import { changeOf, FORM_SECTIONS, problemsAt, rowsOf, type Control, type FormRow, type FormSection, type SettingChange } from './form'
import type { LocatedProblem } from './model'

interface SettingsFormProps {
  /** The text the form edits: the administrator's unsaved text, or the file as it is on disk. */
  text: string
  /** Makes a text with the form's change the unsaved text, which the page checks and saves as if it were typed. */
  onText: (text: string) => void
  /** The check's problems in this file, each shown at the setting it is about. */
  problems: readonly LocatedProblem[]
  onOpenYaml: () => void
}

/** A change the server would not write, under the setting it was for, until the next change. */
type Refused = { path: string; reason: string }

/**
 * appsetting.yaml as switches, choices and numbers: a second editor of the same text. Each change is written into the
 * text by the server, keeping every comment and every other line, and becomes the unsaved text; the check, the review
 * and the save are the editor's own.
 */
export function SettingsForm({ text, onText, problems, onOpenYaml }: SettingsFormProps) {
  const { t } = useTranslation('admin')
  const form = useSettingsForm(text)
  const write = useWriteSettingsForm()
  const [refused, setRefused] = useState<Refused | null>(null)
  const latest = useRef(text)
  const queue = useRef(Promise.resolve())
  useEffect(() => {
    latest.current = text
  }, [text])

  /** One change at a time, each into the text the one before it made, so a quick second change never undoes the first. */
  const change = (next: SettingChange) => {
    const path = next.path.join('.')
    queue.current = queue.current.then(async () => {
      try {
        const answer = await write(latest.current, [next])
        latest.current = answer.text
        setRefused(null)
        onText(answer.text)
      } catch (error) {
        setRefused({ path, reason: isApiError(error) ? error.message : t('common:errors.server') })
      }
    })
  }

  if (form.isPending) return <Skeleton className="m-4 h-96 rounded-xl" />
  if (form.isError) return <ErrorState error={form.error} title={t('form.failed')} onRetry={() => void form.refetch()} className="py-12" />

  const { values, schema } = form.data
  if (values === null) {
    return (
      <StateBlock
        icon={FileWarning}
        title={t('form.unreadable.title')}
        description={t('form.unreadable.description')}
        action={
          <Button type="button" variant="outline" size="sm" onClick={onOpenYaml}>
            {t('form.unreadable.open')}
          </Button>
        }
        className="py-12"
      />
    )
  }

  return (
    <div className={cn('divide-y', form.isPlaceholderData && 'opacity-70')}>
      <p className="px-3 py-2.5 text-xs text-pretty text-muted-foreground md:px-4">{t('form.hint')}</p>
      {FORM_SECTIONS.map((section) => (
        <SectionView key={section.id} section={section} rows={rowsOf(section, schema, values)} problems={problems} refused={refused} onChange={change} />
      ))}
    </div>
  )
}

interface SectionViewProps {
  section: FormSection
  rows: FormRow[]
  problems: readonly LocatedProblem[]
  refused: Refused | null
  onChange: (change: SettingChange) => void
}

function SectionView({ section, rows, problems, refused, onChange }: SectionViewProps) {
  const { t } = useTranslation('admin')
  const own = problems.filter((problem) => problem.path === section.id)
  return (
    <section className="px-3 py-4 md:px-4">
      <h2 className="text-title font-semibold">{t(`form.section.${section.id}`)}</h2>
      <Problems problems={own} />
      <div className="mt-1 divide-y divide-dashed">
        {rows.map((row) => (
          <RowView key={row.path} row={row} problems={problemsAt(problems, row.path)} refused={refused?.path === row.path ? refused.reason : null} onChange={onChange} />
        ))}
      </div>
    </section>
  )
}

interface RowViewProps {
  row: FormRow
  problems: LocatedProblem[]
  refused: string | null
  onChange: (change: SettingChange) => void
}

/** One setting: its label, the path in the YAML, its description, the control, and what the check says about it. */
function RowView({ row, problems, refused, onChange }: RowViewProps) {
  const { t } = useTranslation('admin')
  const id = useId()
  const [noteId, problemsId, refusedId] = [`${id}-note`, `${id}-problems`, `${id}-refused`]
  const label = t(`form.field.${row.path}`)
  const described = {
    id,
    'aria-describedby': [noteId, problems.length > 0 && problemsId, refused !== null && refusedId].filter(Boolean).join(' '),
    'aria-invalid': problems.length > 0 || refused !== null || undefined,
  }
  const control = (() => {
    switch (row.view.kind) {
      case 'control':
        return <ControlView control={row.view.control} label={label} described={described} onChange={(value) => onChange(changeOf(row.path, value))} />
      case 'readOnly':
        return <p className="text-sm font-medium">{t(`form.option.${row.view.value}`)}</p>
      case 'missing':
        return <p className="text-xs text-pretty text-muted-foreground">{t('form.missing')}</p>
      case 'yamlOnly':
        return <p className="text-xs text-pretty text-muted-foreground">{t('form.yamlOnly')}</p>
    }
  })()
  const labelled = row.view.kind === 'control' && row.view.control.kind !== 'choices'
  return (
    <div className="grid gap-x-6 gap-y-2 py-3 md:grid-cols-[minmax(0,1fr)_minmax(12rem,18rem)] md:items-start">
      <div className="min-w-0 space-y-1">
        {labelled ? <Label htmlFor={id}>{label}</Label> : <p className="text-sm leading-none font-medium">{label}</p>}
        <div id={noteId} className="space-y-1 text-xs text-pretty text-muted-foreground">
          <p className="font-mono break-all">{row.path}</p>
          {row.description && <p>{row.description}</p>}
          {row.view.kind === 'readOnly' && <p>{t(`form.readOnly.${row.path}`)}</p>}
        </div>
      </div>
      <div className="min-w-0 space-y-1.5">
        {control}
        <Problems id={problemsId} problems={problems} />
        {refused && (
          <p id={refusedId} className="text-xs text-pretty text-destructive">
            {t('form.notWritten', { reason: refused })}
          </p>
        )}
      </div>
    </div>
  )
}

function Problems({ id, problems }: { id?: string; problems: readonly LocatedProblem[] }) {
  if (problems.length === 0) return null
  return (
    <ul id={id} className="space-y-1">
      {problems.map((problem) => (
        <li key={`${problem.line}:${problem.column}:${problem.message}`} className="text-xs text-pretty text-destructive">
          {problem.message}
        </li>
      ))}
    </ul>
  )
}

interface Described {
  id: string
  'aria-describedby': string
  'aria-invalid': true | undefined
}

interface ControlViewProps {
  control: Control
  label: string
  described: Described
  onChange: (value: SettingChange['value']) => void
}

function ControlView({ control, label, described, onChange }: ControlViewProps) {
  const { t } = useTranslation('admin')
  switch (control.kind) {
    case 'switch':
      return <Switch {...described} checked={control.value} onCheckedChange={onChange} />
    case 'select':
      return (
        <Select value={control.value} onValueChange={onChange}>
          <SelectTrigger {...described} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {control.options.map((option) => (
              <SelectItem key={option} value={option}>
                {t(`form.option.${option}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )
    case 'choices':
      return <Choices control={control} label={label} described={described} onChange={onChange} />
    case 'number':
    case 'text':
      return <TypedInput control={control} described={described} onChange={onChange} />
  }
}

/** A list of choices as checkboxes; a choice added goes last, so the order the file gives the others is kept. */
function Choices({ control, label, described, onChange }: { control: Extract<Control, { kind: 'choices' }>; label: string; described: Described; onChange: (value: string[]) => void }) {
  const { t } = useTranslation('admin')
  return (
    <fieldset id={described.id} aria-describedby={described['aria-describedby']} className="grid grid-cols-2 gap-2.5">
      <legend className="sr-only">{label}</legend>
      {control.options.map((option) => (
        <ChoiceItem
          key={option}
          label={t(`form.option.${option}`)}
          checked={control.value.includes(option)}
          onCheckedChange={(checked) => onChange(checked ? [...control.value, option] : control.value.filter((chosen) => chosen !== option))}
        />
      ))}
    </fieldset>
  )
}

function ChoiceItem({ label, checked, onCheckedChange }: { label: ReactNode; checked: boolean; onCheckedChange: (checked: boolean) => void }) {
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

type Typed = Extract<Control, { kind: 'number' | 'text' }>

/**
 * A number or a text, written when the administrator leaves the field or presses Enter, never at each key: "0." is on
 * its way to a number. A new value in the text, from this field's change or from the YAML tab, replaces what was typed.
 */
function TypedInput({ control, described, onChange }: { control: Typed; described: Described; onChange: (value: number | string) => void }) {
  const { t } = useTranslation('admin')
  const [typed, setTyped] = useState(String(control.value))
  const [invalid, setInvalid] = useState<string | null>(null)
  const [shown, setShown] = useState(control.value)
  if (shown !== control.value) {
    setShown(control.value)
    setTyped(String(control.value))
    setInvalid(null)
  }
  const commit = () => {
    const value = control.kind === 'number' ? Number(typed) : typed
    if (control.kind === 'number' && (typed.trim() === '' || !Number.isFinite(value))) return setInvalid(t('form.notNumber'))
    if (control.kind === 'number' && control.integer && !Number.isInteger(value)) return setInvalid(t('form.notInteger'))
    setInvalid(null)
    if (value !== control.value) onChange(value)
  }
  const number = control.kind === 'number' ? { type: 'number', inputMode: control.integer ? 'numeric' : 'decimal', min: control.min, max: control.max, step: control.integer ? 1 : 'any' } as const : {}
  const invalidId = `${described.id}-invalid`
  return (
    <>
      <Input
        {...described}
        {...number}
        aria-describedby={invalid ? `${described['aria-describedby']} ${invalidId}` : described['aria-describedby']}
        aria-invalid={described['aria-invalid'] ?? (invalid !== null || undefined)}
        value={typed}
        onChange={(event) => setTyped(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => event.key === 'Enter' && commit()}
        className="tabular"
      />
      {invalid && (
        <p id={invalidId} className="text-xs text-destructive">
          {invalid}
        </p>
      )}
    </>
  )
}
