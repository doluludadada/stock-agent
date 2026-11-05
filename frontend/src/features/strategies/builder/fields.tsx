import { useId, useState, type ReactNode } from 'react'
import { useLocale, useTranslation } from '@/i18n'
import { cn } from '@/shared/lib/utils'
import { Input } from '@/shared/ui/input'
import { Label } from '@/shared/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/ui/select'
import { LIMITS } from '../model/catalog'
import { isBlocking, type FieldPath, type ValidationIssue } from '../model/validate'

export type IssueLookup = (path: FieldPath) => ValidationIssue | undefined

function useIssueText() {
  const { t } = useTranslation('builder')
  return (issue: ValidationIssue) => t(`error.${issue.code}`, issue.params)
}

/** An error blocks the save; a warning is advice the backend does not enforce. */
export function FieldError({ id, issue }: { id: string; issue: ValidationIssue | undefined }) {
  const text = useIssueText()
  if (!issue) return null
  const warning = issue.severity === 'warning'
  return (
    <p id={id} className={cn('text-xs font-medium', warning ? 'text-gold' : 'text-destructive')} role={warning ? 'status' : 'alert'}>
      {text(issue)}
    </p>
  )
}

export function Field({ label, htmlFor, children, hint, className }: { label: string; htmlFor: string; children: ReactNode; hint?: ReactNode; className?: string }) {
  return (
    <div className={cn('flex min-w-0 flex-col gap-1.5', className)}>
      <Label htmlFor={htmlFor} className="text-xs font-medium text-muted-foreground">
        {label}
      </Label>
      {children}
      {hint}
    </div>
  )
}

interface NumberFieldProps {
  label: string
  value: number
  onChange: (value: number) => void
  issue?: ValidationIssue
  suffix?: string
  step?: number
  min?: number
  max?: number
  className?: string
  inputClassName?: string
}

/** Keeps the typed text while editing, so "1." or an empty box is allowed until the value parses. */
export function NumberField({ label, value, onChange, issue, suffix, step = 1, min, max, className, inputClassName }: NumberFieldProps) {
  const id = useId()
  const errorId = `${id}-error`
  const [text, setText] = useState(Number.isFinite(value) ? String(value) : '')
  const [synced, setSynced] = useState(value)
  if (!Object.is(synced, value)) {
    setSynced(value)
    const sameNumber = text.trim() !== '' && Number(text) === value
    if (!sameNumber && Number.isFinite(value)) setText(String(value))
  }

  return (
    <Field label={label} htmlFor={id} className={className} hint={<FieldError id={errorId} issue={issue} />}>
      <div className="relative">
        <Input
          id={id}
          inputMode="decimal"
          value={text}
          step={step}
          min={min}
          max={max}
          aria-invalid={isBlocking(issue) ? true : undefined}
          aria-describedby={issue ? errorId : undefined}
          onChange={(event) => {
            const next = event.target.value
            const parsed = next.trim() === '' ? Number.NaN : Number(next)
            setText(next)
            setSynced(parsed)
            onChange(parsed)
          }}
          className={cn('tabular md:h-9', suffix && 'pr-10', inputClassName)}
        />
        {suffix && (
          <span className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-xs text-muted-foreground">{suffix}</span>
        )}
      </div>
    </Field>
  )
}

/** Trading-day offset: today, the previous trading day, or a custom number of trading days back. */
export function DayField({ value, onChange, issue, hint }: { value: number; onChange: (value: number) => void; issue?: ValidationIssue; hint?: string }) {
  const { t } = useTranslation('builder')
  const id = useId()
  const locale = useLocale()
  const [custom, setCustom] = useState(value > 1 || !Number.isFinite(value) || value < 0)
  const choice = custom ? 'custom' : String(value)
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <Label htmlFor={id} className="text-xs font-medium text-muted-foreground">
        {t('operand.day')}
      </Label>
      <div className="flex gap-2">
        <Select
          value={choice}
          onValueChange={(next) => {
            if (next === 'custom') {
              setCustom(true)
              if (value <= 1) onChange(2)
              return
            }
            setCustom(false)
            onChange(Number(next))
          }}
        >
          <SelectTrigger id={id} className="min-w-0 flex-1 md:h-9">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="0">{t('operand.today')}</SelectItem>
            <SelectItem value="1">{t('operand.yesterday')}</SelectItem>
            <SelectItem value="custom">{t('operand.daysAgoCustom')}</SelectItem>
          </SelectContent>
        </Select>
        {custom && (
          <NumberField
            label={t('operand.daysAgo')}
            value={value}
            onChange={onChange}
            min={0}
            max={LIMITS.maxBarsAgo}
            className="w-24 [&>label]:sr-only"
            suffix={t('operand.daysSuffix')}
          />
        )}
      </div>
      {issue && <FieldError id={`${id}-error`} issue={issue} />}
      {hint && <p className="text-[0.6875rem] text-muted-foreground" lang={locale}>{hint}</p>}
    </div>
  )
}
