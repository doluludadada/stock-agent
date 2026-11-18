import { ChevronDown, Minus, Plus, Search, TriangleAlert } from 'lucide-react'
import { memo, useCallback, useEffect, useId, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react'
import { Link, useBlocker, useNavigate, useSearchParams } from 'react-router'
import { toast } from 'sonner'
import { useTranslation } from '@/i18n'
import { useSession, type PageRefusal } from '@/shared/api'
import { useErrorReason } from '@/shared/lib/error-reason'
import { clockTime, useFormat } from '@/shared/lib/format'
import { useKeptDraft } from '@/shared/lib/kept-draft'
import { cn } from '@/shared/lib/utils'
import { Button } from '@/shared/ui/button'
import { Checkbox } from '@/shared/ui/checkbox'
import { ConfirmDialog } from '@/shared/ui/confirm-dialog'
import { ErrorState } from '@/shared/ui/error-state'
import { Input } from '@/shared/ui/input'
import { Label } from '@/shared/ui/label'
import { fitsSegmented, Segmented } from '@/shared/ui/segmented'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/ui/select'
import { Skeleton } from '@/shared/ui/skeleton'
import { Switch } from '@/shared/ui/switch'
import { Textarea } from '@/shared/ui/textarea'
import { useSaveSettings, useSettingsForm } from './api'
import {
  changesOf,
  choiceEntriesOf,
  entriesOf,
  entryKey,
  GROUPS,
  groupsOf,
  inputOf,
  isLongText,
  isNamedOption,
  MANAGED_ELSEWHERE,
  onGrid,
  problemsAt,
  problemsElsewhere,
  shownAmount,
  stepped,
  type Entry,
  type Group,
  type Input as FieldInput,
  type SettingField,
  type SettingGroup,
} from './form'
import { confirmationRefusal, inputsOf, takePendingSave, type PendingSave } from './googleConfirmation'
import { problemMessage, reasonOf, refusalOf, type SettingsProblem } from './model'
import { SaveConfirmation } from './SaveConfirmation'

/** What a save was refused for: the server's problems, each at its setting, or one sentence of the form's own. */
interface Refused {
  problems: SettingsProblem[]
  notice: string | null
}

const NOT_REFUSED: Refused = { problems: [], notice: null }
const noticed = (notice: string): Refused => ({ problems: [], notice })

/** Every setting of the settings files as a form of choices; a save runs on the new settings at once. */
export function SettingsForm() {
  const { t } = useTranslation('admin')
  const form = useSettingsForm()
  if (form.isPending) return <Skeleton className="h-[32rem] rounded-2xl" />
  // A failed reload in the background keeps the form and its unsaved changes; the next reload asks again.
  if (form.data === undefined) return <ErrorState error={form.error} title={t('loadFailed')} onRetry={() => void form.refetch()} className="rounded-2xl border bg-card" />
  return <FormBody fields={form.data} onStale={() => void form.refetch()} />
}

const rowId = (path: string) => `setting-${path}`
const groupId = (group: SettingGroup) => `settings-${group}`
const NO_INPUTS: Record<string, FieldInput> = {}

/** Under this width the form is one long column, so it opens on its first group alone and the others unfold on a tap. */
const NARROW = '(max-width: 47.99rem)'

/** The groups open when the form first shows: every group but the typed ones on a wide screen, the first on a phone. */
function groupsOpenAtFirst(): SettingGroup[] {
  const narrow = window.matchMedia?.(NARROW).matches ?? false
  return narrow ? GROUPS.slice(0, 1) : GROUPS.filter((group) => group !== 'advanced')
}

function FormBody({ fields, onStale }: { fields: SettingField[]; onStale: () => void }) {
  const { t } = useTranslation('admin')
  const reason = useErrorReason()
  const save = useSaveSettings()
  const draft = useKeptDraft<Record<string, FieldInput>>('admin-settings')
  const [inputs, setInputs] = useState(draft.restored ?? NO_INPUTS)
  const [refused, setRefused] = useState(NOT_REFUSED)
  const [confirming, setConfirming] = useState(false)
  const [query, setQuery] = useState('')
  const [opened, setOpened] = useState(groupsOpenAtFirst)
  const { changes, problems } = useMemo(() => changesOf(fields, inputs), [fields, inputs])
  const shown = [...problems, ...refused.problems]
  const changed = useMemo(() => new Set(changes.map((change) => change.path)), [changes])
  const dirty = changes.length > 0 || problems.length > 0
  useEffect(() => draft.track(dirty ? inputs : null), [draft, dirty, inputs])
  const session = useSession()
  const byGoogle = session.status === 'signedIn' && !session.user.has_password
  const toGoogle = useRef(false)
  const blocker = useLeaveGuard(dirty, toGoogle)
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const outcome = params.get('google')

  useEffect(() => {
    const first = fields.find((field) => problemsAt(refused.problems, field.path).length > 0)
    if (first) document.getElementById(rowId(first.path))?.scrollIntoView({ block: 'center' })
  }, [refused, fields])

  const edit = useCallback((path: string, input: FieldInput) => {
    setInputs((current) => ({ ...current, [path]: input }))
    // An edit answers the refusal at its setting, and a refusal about no setting in particular.
    setRefused((current) => ({ notice: null, problems: current.problems.filter((problem) => problem.path !== null && problemsAt([problem], path).length === 0) }))
  }, [])

  const saved = () => {
    setConfirming(false)
    setInputs(NO_INPUTS)
    setRefused(NOT_REFUSED)
    toast.success(t('saved'))
  }

  /** A refusal the form answers itself, above the settings or at the setting it is about. */
  const refuse = (refusal: PageRefusal) => {
    setConfirming(false)
    // A search may hide the setting the refusal is about.
    setQuery('')
    if (refusal.kind === 'conflict') onStale()
    const general = refusal.kind === 'conflict' ? t('conflict') : reasonOf(refusal.error, t, reason)
    setRefused(refusal.kind === 'refused' && refusal.problems.length > 0 ? { problems: refusal.problems, notice: null } : noticed(general))
  }

  /**
   * Back from Google: the save that waited is sent with the id Google's fresh sign-in was granted for, and a save made
   * on another page goes back there once it is saved.
   */
  const sendConfirmed = async (pending: PendingSave) => {
    try {
      await save.mutateAsync({ changes: pending.changes, google_confirmation: pending.id })
      saved()
      if (pending.returnTo) void navigate(pending.returnTo)
    } catch (error) {
      const refusal = refusalOf(error)
      if (refusal.kind === 'refused' || refusal.kind === 'conflict') refuse(refusal)
      else if (refusal.kind === 'googleRequired') setRefused(noticed(t('google.refused.required')))
      else if (refusal.kind === 'throttled') setRefused(noticed(t('google.refused.throttled')))
      else setRefused(noticed(reasonOf(error, t, reason)))
    }
  }

  useEffect(() => {
    if (!outcome) return
    setParams(
      (current) => {
        current.delete('google')
        return current
      },
      { replace: true },
    )
    const pending = takePendingSave()
    if (!pending) return
    // A save made on another page is that page's: the form holds none of it, so nothing holds the way back there.
    if (!pending.returnTo) setInputs(inputsOf(fields, pending.changes))
    if (outcome === 'confirmed') void sendConfirmed(pending)
    else setRefused(noticed(t(`google.refused.${confirmationRefusal(outcome)}`)))
    // The return from Google is handled once, when the form first shows with ?google= in the address.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [outcome])

  const needle = query.trim().toLowerCase()
  const matches = (field: SettingField) =>
    !needle || [t(`form.field.${field.path}`), t(`form.help.${field.path}`), field.path].some((text) => text.toLowerCase().includes(needle))
  const groups = groupsOf(fields.filter(matches))
  const elsewhere = problemsElsewhere(refused.problems, fields)
  // The operator's settings stay folded until asked for, searched for, or a problem sits in one of them.
  // A folded group opens when asked for, when a search looks into it, and when a problem sits in one of its settings.
  const isOpen = (group: SettingGroup) =>
    opened.includes(group) || needle !== '' || fields.some((field) => field.group === group && problemsAt(shown, field.path).length > 0)
  const toggle = (group: SettingGroup) => setOpened((current) => (current.includes(group) ? current.filter((item) => item !== group) : [...current, group]))

  const jump = (group: SettingGroup) => {
    setOpened((current) => (current.includes(group) ? current : [...current, group]))
    document.getElementById(groupId(group))?.scrollIntoView({ block: 'start' })
  }

  return (
    <div className="space-y-4">
      <div className="sticky top-(--topbar-height) z-10 -mx-1 space-y-2 bg-background/95 px-1 py-2 backdrop-blur">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-48 flex-1">
            <Search aria-hidden className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input type="search" value={query} onChange={(event) => setQuery(event.target.value)} aria-label={t('search.label')} placeholder={t('search.placeholder')} className="pl-9" />
          </div>
          {dirty && (
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setInputs(NO_INPUTS)
                setRefused(NOT_REFUSED)
              }}
            >
              {t('discard')}
            </Button>
          )}
          <Button type="button" onClick={() => setConfirming(true)} disabled={changes.length === 0 || problems.length > 0 || save.isPending}>
            {save.isPending && byGoogle ? t('google.saving') : t('save')}
          </Button>
        </div>
        <nav aria-label={t('jump')} className="-mx-1 flex gap-1.5 overflow-x-auto px-1">
          {groups.map((group) => (
            <button
              key={group.id}
              type="button"
              onClick={() => jump(group.id)}
              className="inline-flex min-h-11 shrink-0 items-center rounded-full border bg-card px-3 text-sm whitespace-nowrap text-muted-foreground transition-colors outline-none hover:border-line-strong hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring md:min-h-7 md:text-xs"
            >
              {t(`form.group.${group.id}.title`)}
            </button>
          ))}
        </nav>
      </div>

      {(elsewhere.length > 0 || refused.notice) && (
        <div role="alert" className="flex items-start gap-2.5 rounded-xl border border-destructive/30 bg-danger-soft px-4 py-3 text-sm">
          <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-destructive" />
          <ul className="space-y-1 text-pretty">
            {refused.notice && <li>{refused.notice}</li>}
            {elsewhere.map((problem) => (
              <li key={problem.message}>{problemMessage(problem, t)}</li>
            ))}
          </ul>
        </div>
      )}

      {groups.length === 0 && <p className="py-12 text-center text-sm text-muted-foreground">{t('search.none', { query: query.trim() })}</p>}
      {groups.map((group) => (
        <GroupSection key={group.id} group={group} open={isOpen(group.id)} onToggle={needle === '' ? () => toggle(group.id) : null}>
          {(field) => (
            <SettingRow
              key={field.path}
              field={field}
              input={Object.hasOwn(inputs, field.path) ? inputs[field.path]! : inputOf(field)}
              changed={changed.has(field.path)}
              problems={problemsAt(shown, field.path)}
              onChange={edit}
            />
          )}
        </GroupSection>
      ))}

      <SaveConfirmation
        open={confirming}
        onOpenChange={setConfirming}
        changes={changes}
        onSaved={saved}
        onRefused={refuse}
        onLeave={() => {
          toGoogle.current = true
        }}
      />
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

interface GroupSectionProps {
  group: Group
  open: boolean
  /** Folds or unfolds the group; null while a search holds every group open. */
  onToggle: (() => void) | null
  children: (field: SettingField) => ReactNode
}

/** One group of settings as a card: what the administrator comes to do, in a line, then its settings by YAML section. */
function GroupSection({ group, open, onToggle, children }: GroupSectionProps) {
  const { t } = useTranslation('admin')
  const titleId = `${groupId(group.id)}-title`
  const bodyId = `${groupId(group.id)}-body`
  const title = t(`form.group.${group.id}.title`)
  return (
    <section
      id={groupId(group.id)}
      aria-labelledby={titleId}
      className={cn('scroll-mt-48 rounded-2xl border px-4 py-5 md:scroll-mt-36 md:px-6', group.id === 'advanced' ? 'border-dashed bg-muted/40' : 'bg-card shadow-card')}
    >
      <h2 id={titleId} className="text-title font-semibold">
        {onToggle ? (
          <button type="button" aria-expanded={open} aria-controls={bodyId} onClick={onToggle} className="-my-2 flex min-h-11 w-full items-center justify-between gap-2 rounded-lg text-left outline-none focus-visible:ring-2 focus-visible:ring-ring">
            {title}
            <ChevronDown aria-hidden className={cn('size-4 shrink-0 text-muted-foreground transition-transform', open && 'rotate-180')} />
          </button>
        ) : (
          title
        )}
      </h2>
      <p className="mt-1 text-sm text-pretty text-muted-foreground">{t(`form.group.${group.id}.description`)}</p>
      {open && (
        <div id={bodyId}>
          {group.parts.map((part) => (
            <div key={`${part.section}/${part.heading}`} className="mt-4">
              {(group.parts.length > 1 || part.heading) && (
                <h3 className="eyebrow">
                  {t(`form.section.${part.section}`)}
                  {part.heading && ` · ${t(`form.heading.${part.heading}`)}`}
                </h3>
              )}
              <div className="divide-y divide-dashed">{part.fields.map(children)}</div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

/** How a setting's values read: a number with its unit, an option by its name, and the file's own value marked as such. */
function useWording() {
  const { t } = useTranslation('admin')
  const format = useFormat()
  return useMemo(() => {
    const amount = (value: number, unit: SettingField['unit']): string => {
      const shown = shownAmount(value, unit)
      const text = format.number(shown.value, shown.decimals)
      return unit ? t(`form.unit.${unit}`, { value: text }) : text
    }
    // A built-in strategy's id is an option the server names at runtime, so it shows as it is; a time of day shows to the minute.
    const option = (value: string): string => (isNamedOption(value) ? t(`form.option.${value}`, { defaultValue: value }) : clockTime(value))
    const value = (field: SettingField, held: FieldInput): string => {
      if (held === null) return t('form.notSet')
      if (typeof held === 'number') return amount(held, field.unit)
      return typeof held === 'string' && (field.kind === 'choice' || field.kind === 'choices') ? option(held) : String(held)
    }
    const entry = (field: SettingField, item: Entry): string => (item.custom ? t('form.custom', { value: value(field, item.value) }) : value(field, item.value))
    return { value, entry }
  }, [t, format])
}

/** Whether a choice shows as a row of buttons: its options' names fit side by side, none of them a custom value. */
const isSegmented = (field: SettingField, entries: readonly Entry[], labels: readonly string[]) =>
  field.kind === 'choice' && entries.every((entry) => !entry.custom) && fitsSegmented(labels)

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
  const wording = useWording()
  const id = useId()
  const [helpId, problemsId] = [`${id}-help`, `${id}-problems`]
  const wide = field.kind === 'lines' || field.kind === 'structure' || isLongText(field)
  const described: Described = {
    id,
    'aria-describedby': problems.length > 0 ? `${helpId} ${problemsId}` : helpId,
    'aria-invalid': problems.length > 0 || undefined,
  }
  const label = t(`form.field.${field.path}`)
  // A control made of several parts names itself; one control takes the label.
  const entries = field.kind === 'choice' ? entriesOf(field) : []
  const grouped = field.kind === 'choices' || field.kind === 'range' || isSegmented(field, entries, entries.map((entry) => wording.entry(field, entry)))
  const managedAt = MANAGED_ELSEWHERE[field.path]
  const fixed = field.restart_only || managedAt !== undefined
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
          {fixed || grouped ? <p className="text-sm leading-none font-medium">{label}</p> : <Label htmlFor={id}>{label}</Label>}
        </div>
        <div id={helpId} className="space-y-1 text-xs text-pretty text-muted-foreground">
          <p>{t(`form.help.${field.path}`)}</p>
          {field.restart_only && <p>{t('form.restartOnly')}</p>}
          {managedAt !== undefined && (
            <p>
              <Link to={managedAt} className="tap text-brand underline-offset-4 hover:underline">
                {t(`form.managedAt.${field.path}`)}
              </Link>
            </p>
          )}
        </div>
      </div>
      <div className="min-w-0 space-y-1.5">
        {fixed ? (
          <p className="text-sm font-medium">{wording.value(field, field.value)}</p>
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

/** A change in one setting renders that row only, not the two hundred others. */
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

/**
 * The control the setting's kind gets. All but the last three are chosen, never typed: a switch, buttons or a list
 * for a choice, checkboxes, a list of steps, a slider with minus and plus, a date, a time; then text, lines and JSON.
 */
function Control({ field, input, label, described, onChange }: ControlProps) {
  const { t } = useTranslation('admin')
  const text = typeof input === 'string' ? input : ''
  switch (field.kind) {
    case 'switch':
      return <Switch {...described} checked={input === true} onCheckedChange={onChange} />
    case 'choice':
    case 'steps':
      return <Pick field={field} input={input} label={label} described={described} onChange={onChange} />
    case 'choices':
      return <Choices field={field} chosen={Array.isArray(input) ? input.map(String) : []} label={label} described={described} onChange={onChange} />
    case 'range':
      return <Range field={field} value={typeof input === 'number' ? input : null} label={label} described={described} onChange={onChange} />
    case 'date':
    case 'time':
      return <Input {...described} type={field.kind} value={text} onChange={(event) => onChange(event.target.value)} className="tabular" />
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

/** One of a setting's options or steps: a row of buttons for a few, a list for more. */
function Pick({ field, input, label, described, onChange }: ControlProps) {
  const { t } = useTranslation('admin')
  const wording = useWording()
  const entries = entriesOf(field)
  const picked = entries.find((entry) => entry.key === entryKey(input))
  const pick = (key: string) => {
    const entry = entries.find((item) => item.key === key)
    if (entry) onChange(entry.value)
  }
  if (isSegmented(field, entries, entries.map((entry) => wording.entry(field, entry)))) {
    return (
      <Segmented
        label={label}
        describedBy={described['aria-describedby']}
        value={picked?.key ?? ''}
        onChange={pick}
        options={entries.map((entry) => ({ value: entry.key, label: wording.entry(field, entry) }))}
        className="md:w-full"
      />
    )
  }
  return (
    <Select value={picked?.key ?? ''} onValueChange={pick}>
      <SelectTrigger {...described} className="tabular w-full">
        <SelectValue placeholder={t('form.notSet')} />
      </SelectTrigger>
      <SelectContent>
        {entries.map((entry) => (
          <SelectItem key={entry.key} value={entry.key} className="tabular">
            {wording.entry(field, entry)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

interface ChoicesProps {
  field: SettingField
  chosen: string[]
  label: string
  described: Described
  onChange: (chosen: string[]) => void
}

/** A list of choices as checkboxes; a choice added goes last, so the order the file gives the others is kept. */
function Choices({ field, chosen, label, described, onChange }: ChoicesProps) {
  const wording = useWording()
  return (
    <fieldset id={described.id} aria-describedby={described['aria-describedby']} className="grid grid-cols-2 gap-2.5">
      <legend className="sr-only">{label}</legend>
      {choiceEntriesOf(field).map((entry) => (
        <ChoiceItem
          key={entry.key}
          label={wording.entry(field, entry)}
          checked={chosen.includes(entry.key)}
          onCheckedChange={(checked) => onChange(checked ? [...chosen, entry.key] : chosen.filter((item) => item !== entry.key))}
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

interface RangeProps {
  field: SettingField
  value: number | null
  label: string
  described: Described
  onChange: (value: number | null) => void
}

/**
 * A number on a scale: minus and plus move it one step, and a slider too where the scale has both ends. The value
 * reads as text with its unit; a value the file holds between two steps says so and stays until moved.
 */
function Range({ field, value, label, described, onChange }: RangeProps) {
  const { t } = useTranslation('admin')
  const wording = useWording()
  const { minimum, maximum } = field
  const bounded = typeof minimum === 'number' && typeof maximum === 'number'
  const amount = wording.value(field, value)
  const reading = value !== null && !onGrid(field, value) ? t('form.custom', { value: amount }) : amount
  const step = (direction: 1 | -1, name: string, Icon: typeof Plus, end: number | null | undefined) => (
    <Button type="button" variant="outline" size="icon" aria-label={name} disabled={value !== null && typeof end === 'number' && value === end} onClick={() => onChange(stepped(field, value, direction))}>
      <Icon aria-hidden />
    </Button>
  )
  return (
    <fieldset id={described.id} aria-describedby={described['aria-describedby']} className="min-w-0 space-y-1.5">
      <legend className="sr-only">{label}</legend>
      <div className="flex items-center gap-2">
        {step(-1, t('form.decrease', { label }), Minus, minimum)}
        {bounded ? (
          <input
            type="range"
            aria-label={label}
            aria-valuetext={reading}
            aria-invalid={described['aria-invalid']}
            min={minimum}
            max={maximum}
            step={field.step ?? 'any'}
            value={value ?? minimum}
            onChange={(event) => onChange(Number(event.target.value))}
            className="h-11 min-w-0 flex-1 cursor-pointer accent-brand md:h-8"
          />
        ) : (
          <output className="tabular min-w-0 flex-1 text-center text-sm font-medium">{reading}</output>
        )}
        {step(1, t('form.increase', { label }), Plus, maximum)}
      </div>
      {(bounded || (field.nullable && value !== null)) && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          {bounded && <output className="tabular text-sm font-medium">{reading}</output>}
          {field.nullable && value !== null && (
            <Button type="button" variant="ghost" size="sm" onClick={() => onChange(null)}>
              {t('form.unset')}
            </Button>
          )}
        </div>
      )}
    </fieldset>
  )
}

/**
 * Asks before leaving the page while a change is not saved. Closing or reloading the tab asks the browser's own
 * question, except on the way to Google to confirm a save: the changes wait in the session storage and come back.
 */
function useLeaveGuard(unsaved: boolean, toGoogle: RefObject<boolean>) {
  useEffect(() => {
    if (!unsaved) return
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!toGoogle.current) event.preventDefault()
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [unsaved, toGoogle])
  return useBlocker(({ currentLocation, nextLocation }) => unsaved && currentLocation.pathname !== nextLocation.pathname)
}
