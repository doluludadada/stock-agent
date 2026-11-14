import { useSearchParams } from 'react-router'
import { useTranslation } from '@/i18n'
import { Button } from '@/shared/ui/button'
import { GoogleMark } from '@/shared/ui/google-mark'
import { useAuthStatus } from './api'
import { FormAlert } from './AuthForm'

/** Where the browser goes to sign in with Google: a navigation the server answers with a redirect, never a fetch. */
export const GOOGLE_START = '/v1/auth/google/start'

/** What the server says in `?google=` when a sign-in with Google ended without a session; anything else reads as `failed`. */
const REFUSALS = [
  'not_offered',
  'flow_missing',
  'state_mismatch',
  'cancelled',
  'provider_failed',
  'token_refused',
  'email_unverified',
  'not_allowed',
  'deactivated',
  'throttled',
] as const

type Refusal = (typeof REFUSALS)[number]

function isRefusal(value: string): value is Refusal {
  return REFUSALS.some((refusal) => refusal === value)
}

/**
 * The sign-in with Google of the sign-in and the setup screens, above their form: the link while the site offers it,
 * and why the last try ended without a session. It renders nothing on a site without Google and without a refusal.
 */
export function GoogleSignIn({ lead }: { lead?: string }) {
  const { t } = useTranslation('auth')
  const status = useAuthStatus()
  const [params] = useSearchParams()
  const outcome = params.get('google')
  const offered = status.data?.google_sign_in === true
  if (!offered && !outcome) return null
  return (
    <div className="grid gap-4">
      {outcome && <FormAlert>{t(`google.refused.${isRefusal(outcome) ? outcome : 'failed'}`)}</FormAlert>}
      {offered && (
        <>
          {lead && <p className="text-sm text-pretty text-muted-foreground">{lead}</p>}
          <Button asChild variant="outline" size="lg" className="w-full">
            <a href={GOOGLE_START}>
              <GoogleMark className="size-4.5 shrink-0" />
              {t('google.signIn')}
            </a>
          </Button>
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span aria-hidden className="h-px flex-1 bg-border" />
            {t('google.or')}
            <span aria-hidden className="h-px flex-1 bg-border" />
          </div>
        </>
      )}
    </div>
  )
}
