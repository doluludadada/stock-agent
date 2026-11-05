import { UserPlus } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { useTranslation } from '@/i18n'
import { isApiError, useSession } from '@/shared/api'
import { Button } from '@/shared/ui/button'
import { Field } from '@/shared/ui/field'
import { Input } from '@/shared/ui/input'
import { PasswordInput } from '@/shared/ui/password-input'
import { Skeleton } from '@/shared/ui/skeleton'
import { StateBlock } from '@/shared/ui/state-block'
import { useAuthStatus, useRegister, useSetUp, useSignIn } from './api'
import { AuthFrame, FormAlert, NewAccountForm } from './AuthForm'

const linkClass = 'inline-flex min-h-11 items-center font-medium text-brand underline-offset-4 hover:underline md:min-h-0'

/** The first visit: the administrator, with the one-time code the server printed on its console; signed in at once. */
export function SetupScreen({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation('auth')
  const setUp = useSetUp()
  return (
    <AuthFrame eyebrow={t('setup.eyebrow')} title={t('setup.title')} lead={t('setup.lead')} footer={t('setup.note')}>
      <NewAccountForm
        withSetupCode
        submitLabel={t('setup.submit')}
        onSubmit={(account) =>
          setUp.mutateAsync({ setup_code: account.setupCode, username: account.username, email: account.email, password: account.password }).then(onDone)
        }
      />
    </AuthFrame>
  )
}

type SignInProblem = { kind: 'wrong' } | { kind: 'rateLimited'; minutes: number } | { kind: 'failed' }

function signInProblem(error: unknown): SignInProblem {
  if (isApiError(error, 'unauthorized')) return { kind: 'wrong' }
  if (isApiError(error, 'rateLimited')) return { kind: 'rateLimited', minutes: Math.max(1, Math.ceil((error.retryAfter ?? 60) / 60)) }
  return { kind: 'failed' }
}

/** Sign in with the username or the email; `onDone` goes back to the page that asked for it. */
export function SignInScreen({ registerHref, onDone }: { registerHref: string; onDone: () => void }) {
  const { t } = useTranslation('auth')
  const status = useAuthStatus()
  const current = useSession()
  const signIn = useSignIn()
  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [problem, setProblem] = useState<SignInProblem | null>(null)
  const ended = current.status === 'signedOut' && current.ended

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!identifier.trim() || !password) return
    setProblem(null)
    signIn.mutate({ identifier: identifier.trim(), password }, { onSuccess: onDone, onError: (error) => setProblem(signInProblem(error)) })
  }

  return (
    <AuthFrame
      title={t('signIn.title')}
      lead={t('signIn.lead')}
      footer={
        status.data?.registration_open === false ? (
          t('signIn.closed')
        ) : (
          <>
            {t('signIn.noAccount')}{' '}
            <Link to={registerHref} className={linkClass}>
              {t('signIn.registerLink')}
            </Link>
          </>
        )
      }
    >
      <form onSubmit={submit} className="grid gap-4">
        {ended && !problem && <p className="rounded-lg bg-gold-soft px-3 py-2.5 text-sm text-gold">{t('signIn.ended')}</p>}
        <Field label={t('field.identifier')}>
          <Input value={identifier} onChange={(event) => setIdentifier(event.target.value)} autoComplete="username" autoCapitalize="none" spellCheck={false} required />
        </Field>
        <Field label={t('field.password')}>
          <PasswordInput
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            showLabel={t('showPassword')}
            hideLabel={t('hidePassword')}
            required
          />
        </Field>
        {problem && (
          <FormAlert>{problem.kind === 'wrong' ? t('signIn.wrong') : problem.kind === 'rateLimited' ? t('alert.rateLimited', { minutes: problem.minutes }) : t('alert.failed')}</FormAlert>
        )}
        <Button type="submit" size="lg" className="mt-1 w-full" disabled={signIn.isPending || !identifier.trim() || !password}>
          {t('signIn.submit')}
        </Button>
      </form>
    </AuthFrame>
  )
}

/** A new user, signed in at once, or the note that registration is closed. */
export function RegisterScreen({ signInHref, onDone }: { signInHref: string; onDone: () => void }) {
  const { t } = useTranslation('auth')
  const status = useAuthStatus()
  const register = useRegister()
  if (status.isPending) return <Skeleton className="h-96 w-full max-w-sm rounded-2xl" />
  if (status.data?.registration_open === false) {
    return (
      <StateBlock
        icon={UserPlus}
        title={t('register.closedTitle')}
        description={t('register.closedDescription')}
        action={
          <Button asChild variant="outline">
            <Link to={signInHref}>{t('register.signInLink')}</Link>
          </Button>
        }
      />
    )
  }
  return (
    <AuthFrame
      title={t('register.title')}
      lead={t('register.lead')}
      footer={
        <>
          {t('register.haveAccount')}{' '}
          <Link to={signInHref} className={linkClass}>
            {t('register.signInLink')}
          </Link>
        </>
      }
    >
      <NewAccountForm
        submitLabel={t('register.submit')}
        onSubmit={(account) => register.mutateAsync({ username: account.username, email: account.email, password: account.password }).then(onDone)}
      />
    </AuthFrame>
  )
}
