import { LoaderCircle, LockKeyhole, TriangleAlert } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent, type RefObject } from 'react'
import { useTranslation } from '@/i18n'
import { Button } from '@/shared/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/shared/ui/dialog'
import { Field } from '@/shared/ui/field'
import { PasswordInput } from '@/shared/ui/password-input'
import { ChangeSummary, LineChanges, ProblemList } from './CheckDetails'
import { reasonOf, type SaveRefusal, type SettingsEdit } from './model'

/** The refusals the dialog answers in place; the page answers a conflict or a text the app would not start with. */
export type DialogRefusal = Extract<SaveRefusal, { kind: 'wrongPassword' | 'throttled' | 'failed' }>

export type Review = { kind: 'loading' } | { kind: 'failed'; error: unknown } | { kind: 'ready'; edit: SettingsEdit }

interface ReviewDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description: string
  confirmLabel: string
  review: Review
  /** Opens the line changes at once, as a restore does: the version coming back is what the reader looks at. */
  showLines?: boolean
  /** Why it cannot go ahead, such as a version the app would not start with; shown instead of the confirm button. */
  blocked?: string | null
  /** Sends the save or the restore with the administrator's password; null once it went through. */
  onConfirm: (password: string) => Promise<DialogRefusal | null>
  /** When the server takes a password again after too many wrong ones, as a time in ms; null when it takes one now. */
  throttledUntil: number | null
  onThrottled: (until: number) => void
}

/**
 * The last look before a save or a restore: what it changes, the line changes, and the administrator's password,
 * which every save and restore needs. A wrong password, the attempt limit and a lost connection keep the dialog open.
 */
export function ReviewDialog({ open, onOpenChange, title, description, ...form }: ReviewDialogProps) {
  const [pending, setPending] = useState(false)
  const passwordField = useRef<HTMLInputElement>(null)
  return (
    <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <DialogContent
        className="max-h-[min(92dvh,52rem)] gap-5 overflow-y-auto sm:max-w-xl"
        onOpenAutoFocus={(event) => {
          if (!passwordField.current) return
          event.preventDefault()
          passwordField.current.focus()
        }}
      >
        <DialogHeader>
          <DialogTitle className="pr-8 text-title">{title}</DialogTitle>
          <DialogDescription className="text-pretty">{description}</DialogDescription>
        </DialogHeader>
        <ReviewForm {...form} onCancel={() => onOpenChange(false)} pending={pending} setPending={setPending} passwordField={passwordField} />
      </DialogContent>
    </Dialog>
  )
}

type ReviewFormProps = Omit<ReviewDialogProps, 'open' | 'onOpenChange' | 'title' | 'description'> & {
  onCancel: () => void
  pending: boolean
  setPending: (pending: boolean) => void
  passwordField: RefObject<HTMLInputElement | null>
}

/** The dialog's body; it mounts each time the dialog opens, so a password typed before never comes back. */
function ReviewForm({ confirmLabel, review, showLines, blocked, onConfirm, throttledUntil, onThrottled, onCancel, pending, setPending, passwordField }: ReviewFormProps) {
  const { t } = useTranslation('admin')
  const [password, setPassword] = useState('')
  const [refusal, setRefusal] = useState<DialogRefusal | null>(null)
  const wait = useSecondsUntil(throttledUntil)
  const edit = review.kind === 'ready' ? review.edit : null
  const ready = edit !== null && !blocked

  // A restore's comparison arrives after the dialog opened: the password field takes the focus once it appears.
  useEffect(() => {
    if (ready) passwordField.current?.focus()
  }, [ready, passwordField])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (pending || wait > 0 || !edit || blocked || !password) return
    setPending(true)
    setRefusal(null)
    const result = await onConfirm(password)
    setPending(false)
    if (!result) return
    setRefusal(result)
    if (result.kind === 'throttled') onThrottled(Date.now() + (result.retryAfter ?? 60) * 1000)
    if (result.kind === 'wrongPassword' || result.kind === 'throttled') {
      setPassword('')
      requestAnimationFrame(() => passwordField.current?.focus())
    }
  }

  const message =
    wait > 0
      ? wait >= 60
        ? t('review.throttledMinutes', { minutes: Math.floor(wait / 60), seconds: wait % 60 })
        : t('review.throttledSeconds', { seconds: wait })
      : refusal?.kind === 'failed'
        ? t('review.failed', { reason: reasonOf(refusal.error, t) })
        : null

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      {review.kind === 'loading' && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" aria-live="polite">
          <LoaderCircle aria-hidden className="size-4 animate-spin" />
          {t('history.loading')}
        </p>
      )}
      {review.kind === 'failed' && (
        <p className="flex items-start gap-2 text-sm text-destructive" role="alert">
          <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
          {t('history.restoreFailed', { reason: reasonOf(review.error, t) })}
        </p>
      )}
      {edit && (
        <>
          {edit.problems.length > 0 ? <ProblemList problems={edit.problems} file={edit.file} /> : <ChangeSummary edit={edit} />}
          <LineChanges diff={edit.diff} defaultOpen={showLines} />
        </>
      )}
      {edit && !blocked && (
        <div className="space-y-3 rounded-xl border bg-muted/60 p-3.5">
          <p className="flex items-start gap-2 text-sm text-pretty">
            <LockKeyhole aria-hidden className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
            {t('review.passwordWhy')}
          </p>
          <Field label={t('review.password')} error={refusal?.kind === 'wrongPassword' ? t('review.wrongPassword') : null}>
            <PasswordInput
              ref={passwordField}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              showLabel={t('review.show')}
              hideLabel={t('review.hide')}
              disabled={pending || wait > 0}
              className="bg-card"
            />
          </Field>
        </div>
      )}
      {blocked && (
        <p className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-danger-soft px-3 py-2 text-sm" role="alert">
          <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-destructive" />
          {blocked}
        </p>
      )}
      {message && (
        <p className="flex items-start gap-2 text-sm text-destructive" role="alert">
          <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
          {message}
        </p>
      )}
      <DialogFooter className="gap-2 sm:gap-2">
        <Button type="button" variant="outline" onClick={onCancel} disabled={pending}>
          {t('review.cancel')}
        </Button>
        {!blocked && (
          <Button type="submit" disabled={pending || wait > 0 || !edit || !password}>
            {pending && <LoaderCircle aria-hidden className="animate-spin" />}
            {pending ? t('review.saving') : confirmLabel}
          </Button>
        )}
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
