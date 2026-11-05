import { CircleAlert } from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'
import { useTranslation } from '@/i18n'
import { isApiError } from '@/shared/api'
import { Button } from '@/shared/ui/button'
import { Field } from '@/shared/ui/field'
import { Input } from '@/shared/ui/input'
import { PasswordInput } from '@/shared/ui/password-input'
import { accountProblems, EMPTY_ACCOUNT_FORM, type AccountField, type AccountForm, type AccountProblem, type AccountProblems } from './model'

interface AuthFrameProps {
  eyebrow?: string
  title: string
  lead: string
  children: ReactNode
  footer?: ReactNode
}

/** The heading, form and footer of the setup, sign-in and register screens. */
export function AuthFrame({ eyebrow, title, lead, children, footer }: AuthFrameProps) {
  return (
    <div className="w-full max-w-sm space-y-7">
      <header className="space-y-2">
        {eyebrow && <p className="eyebrow text-brand">{eyebrow}</p>}
        <h1 className="display">{title}</h1>
        <p className="text-sm text-pretty text-muted-foreground">{lead}</p>
      </header>
      {children}
      {footer && <div className="border-t pt-5 text-sm text-muted-foreground">{footer}</div>}
    </div>
  )
}

/** A form-level problem, such as a wrong password or a server that did not answer. */
export function FormAlert({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="flex items-start gap-2 rounded-lg bg-danger-soft px-3 py-2.5 text-sm text-destructive">
      <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
      <span>{children}</span>
    </p>
  )
}

/** What a refusal means for a form: a problem under one field, or a line above the button. */
type Refusal = { field: AccountField; problem: AccountProblem } | { alert: 'failed' | 'closed' | 'alreadySetUp' | 'rateLimited'; minutes?: number }

const FORMAT_PROBLEM: Partial<Record<AccountField, AccountProblem>> = { username: 'usernameFormat', email: 'emailFormat', password: 'passwordShort' }

/**
 * Reads the server's answer to a setup or a registration. The setup's only 403 is a wrong code and its 409 a site
 * already set up; a registration's 403 is registration closed and its 409 a taken name, which the server names only
 * in its message.
 */
function refusalOf(error: unknown, setup: boolean): Refusal {
  if (!isApiError(error)) return { alert: 'failed' }
  switch (error.kind) {
    case 'forbidden':
      return setup ? { field: 'setupCode', problem: 'wrongCode' } : { alert: 'closed' }
    case 'conflict':
      if (setup) return { alert: 'alreadySetUp' }
      return { field: /\bemail\b/i.test(error.message) ? 'email' : 'username', problem: 'taken' }
    case 'invalid': {
      const field = error.problems[0]?.location.at(-1)
      const named = field === 'setup_code' ? 'setupCode' : field
      if (named === 'username' || named === 'email' || named === 'password' || named === 'setupCode') {
        return { field: named, problem: FORMAT_PROBLEM[named] ?? 'required' }
      }
      return { alert: 'failed' }
    }
    case 'rateLimited':
      return { alert: 'rateLimited', minutes: Math.max(1, Math.ceil((error.retryAfter ?? 60) / 60)) }
    default:
      return { alert: 'failed' }
  }
}

export interface NewAccount {
  setupCode: string
  username: string
  email: string
  password: string
}

interface NewAccountFormProps {
  submitLabel: string
  /** The first-time setup also asks for the code the server printed on its console. */
  withSetupCode?: boolean
  /** Sends the account to the server; a refusal comes back as the rejected promise. */
  onSubmit: (account: NewAccount) => Promise<unknown>
}

/** Username, email and the password twice: the administrator's setup and every registration. */
export function NewAccountForm({ submitLabel, withSetupCode = false, onSubmit }: NewAccountFormProps) {
  const { t } = useTranslation('auth')
  const [form, setForm] = useState<AccountForm>(EMPTY_ACCOUNT_FORM)
  const [tried, setTried] = useState(false)
  const [pending, setPending] = useState(false)
  const [refusal, setRefusal] = useState<Refusal | null>(null)
  const local = tried ? accountProblems(form, withSetupCode) : {}
  const fromServer: AccountProblems = refusal && 'field' in refusal ? { [refusal.field]: refusal.problem } : {}
  const problems: AccountProblems = { ...fromServer, ...local }

  const change = (field: AccountField, value: string) => {
    setForm({ ...form, [field]: value })
    if (refusal && 'field' in refusal && refusal.field === field) setRefusal(null)
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setTried(true)
    if (Object.keys(accountProblems(form, withSetupCode)).length > 0) return
    setPending(true)
    setRefusal(null)
    try {
      await onSubmit({ setupCode: form.setupCode.trim(), username: form.username.trim(), email: form.email.trim(), password: form.password })
    } catch (error) {
      setRefusal(refusalOf(error, withSetupCode))
      setPending(false)
    }
  }

  const message = (field: AccountField) => {
    const problem = problems[field]
    if (!problem) return null
    return problem === 'taken' ? t(field === 'email' ? 'problem.taken.email' : 'problem.taken.username') : t(`problem.${problem}`)
  }

  return (
    <form noValidate onSubmit={(event) => void submit(event)} className="grid gap-4">
      {withSetupCode && (
        <Field label={t('field.setupCode')} hint={t('hint.setupCode')} error={message('setupCode')}>
          <Input value={form.setupCode} onChange={(event) => change('setupCode', event.target.value)} autoComplete="one-time-code" autoCapitalize="none" spellCheck={false} className="font-mono" />
        </Field>
      )}
      <Field label={t('field.username')} hint={t('hint.username')} error={message('username')}>
        <Input value={form.username} onChange={(event) => change('username', event.target.value)} autoComplete="username" autoCapitalize="none" spellCheck={false} />
      </Field>
      <Field label={t('field.email')} error={message('email')}>
        <Input type="email" value={form.email} onChange={(event) => change('email', event.target.value)} autoComplete="email" inputMode="email" />
      </Field>
      <Field label={t('field.password')} hint={t('hint.password')} error={message('password')}>
        <PasswordInput value={form.password} onChange={(event) => change('password', event.target.value)} autoComplete="new-password" showLabel={t('showPassword')} hideLabel={t('hidePassword')} />
      </Field>
      <Field label={t('field.confirm')} error={message('confirm')}>
        <PasswordInput value={form.confirm} onChange={(event) => change('confirm', event.target.value)} autoComplete="new-password" showLabel={t('showPassword')} hideLabel={t('hidePassword')} />
      </Field>
      {refusal && 'alert' in refusal && <FormAlert>{t(`alert.${refusal.alert}`, { minutes: refusal.minutes })}</FormAlert>}
      <Button type="submit" size="lg" className="mt-1 w-full" disabled={pending}>
        {submitLabel}
      </Button>
    </form>
  )
}
