import { LoaderCircle, TriangleAlert } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent, type ReactNode, type RefObject } from 'react'
import { useTranslation } from '@/i18n'
import { useErrorReason } from '@/shared/lib/error-reason'
import { Button } from '@/shared/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/shared/ui/dialog'
import { Field } from '@/shared/ui/field'
import { PasswordInput } from '@/shared/ui/password-input'
import { reasonOf, type SaveRefusal } from './model'

/** The refusals the dialog answers in place; the form answers the others. */
export type DialogRefusal = Extract<SaveRefusal, { kind: 'wrongPassword' | 'throttled' | 'failed' }>

interface PasswordDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Sends the save with the administrator's password; null once the dialog has nothing left to say. */
  onConfirm: (password: string) => Promise<DialogRefusal | null>
  /** A page's own title and sentence, in place of the settings page's. */
  title?: string
  description?: string
  /** What the dialog shows above the password: what the save changes, and a field of the page's own. */
  children?: ReactNode
  /** False holds the confirm button until the page's own field is filled. */
  ready?: boolean
}

/**
 * Every save needs the administrator's password again, so a stolen session alone changes no setting. A wrong password,
 * the attempt limit and a lost connection keep the dialog open.
 */
export function PasswordDialog({ open, onOpenChange, onConfirm, title, description, children, ready = true }: PasswordDialogProps) {
  const { t } = useTranslation('admin')
  const [pending, setPending] = useState(false)
  const [throttledUntil, setThrottledUntil] = useState<number | null>(null)
  const field = useRef<HTMLInputElement>(null)
  return (
    <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <DialogContent
        className="gap-5 sm:max-w-md"
        onOpenAutoFocus={(event) => {
          if (!field.current) return
          event.preventDefault()
          field.current.focus()
        }}
      >
        <DialogHeader>
          <DialogTitle className="text-title">{title ?? t('password.title')}</DialogTitle>
          <DialogDescription className="text-pretty">{description ?? t('password.description')}</DialogDescription>
        </DialogHeader>
        {children}
        <PasswordForm
          field={field}
          onConfirm={onConfirm}
          onCancel={() => onOpenChange(false)}
          pending={pending}
          setPending={setPending}
          throttledUntil={throttledUntil}
          onThrottled={setThrottledUntil}
          ready={ready}
        />
      </DialogContent>
    </Dialog>
  )
}

interface PasswordFormProps {
  field: RefObject<HTMLInputElement | null>
  onConfirm: PasswordDialogProps['onConfirm']
  onCancel: () => void
  pending: boolean
  setPending: (pending: boolean) => void
  throttledUntil: number | null
  onThrottled: (until: number) => void
  ready: boolean
}

/** The dialog's body; it mounts each time the dialog opens, so a password typed before never comes back. */
function PasswordForm({ field, onConfirm, onCancel, pending, setPending, throttledUntil, onThrottled, ready }: PasswordFormProps) {
  const { t } = useTranslation('admin')
  const reason = useErrorReason()
  const [password, setPassword] = useState('')
  const [refusal, setRefusal] = useState<DialogRefusal | null>(null)
  const wait = useSecondsUntil(throttledUntil)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (pending || wait > 0 || !password || !ready) return
    setPending(true)
    setRefusal(null)
    const result = await onConfirm(password)
    setPending(false)
    if (!result) return
    setRefusal(result)
    if (result.kind === 'throttled') onThrottled(Date.now() + (result.retryAfter ?? 60) * 1000)
    if (result.kind === 'wrongPassword' || result.kind === 'throttled') {
      setPassword('')
      requestAnimationFrame(() => field.current?.focus())
    }
  }

  const message =
    wait > 0
      ? wait >= 60
        ? t('password.throttledMinutes', { minutes: Math.floor(wait / 60), seconds: wait % 60 })
        : t('password.throttledSeconds', { seconds: wait })
      : refusal?.kind === 'failed'
        ? t('password.failed', { reason: reasonOf(refusal.error, t, reason) })
        : null

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      <Field label={t('password.label')} error={refusal?.kind === 'wrongPassword' ? t('password.wrong') : null}>
        <PasswordInput
          ref={field}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="current-password"
          showLabel={t('password.show')}
          hideLabel={t('password.hide')}
          disabled={pending || wait > 0}
        />
      </Field>
      {message && (
        <p className="flex items-start gap-2 text-sm text-destructive" role="alert">
          <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
          {message}
        </p>
      )}
      <DialogFooter className="gap-2 sm:gap-2">
        <Button type="button" variant="outline" onClick={onCancel} disabled={pending}>
          {t('password.cancel')}
        </Button>
        <Button type="submit" disabled={pending || wait > 0 || !password || !ready}>
          {pending && <LoaderCircle aria-hidden className="animate-spin" />}
          {pending ? t('password.saving') : t('password.confirm')}
        </Button>
      </DialogFooter>
    </form>
  )
}

/** Whole seconds left until `until` (ms), counting down once a second; 0 once it passed or when there is none. */
function useSecondsUntil(until: number | null): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (until === null) return
    const tick = () => setNow(Date.now())
    const first = window.setTimeout(tick, 0)
    const timer = window.setInterval(tick, 1000)
    return () => {
      window.clearTimeout(first)
      window.clearInterval(timer)
    }
  }, [until])
  return until === null ? 0 : Math.max(0, Math.ceil((until - now) / 1000))
}
