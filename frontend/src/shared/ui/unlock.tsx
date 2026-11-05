import { KeyRound, LockKeyhole } from 'lucide-react'
import { useId, useState, type FormEvent, type ReactNode } from 'react'
import { useTranslation } from '@/i18n'
import { session, useSession, type Scope } from '@/shared/api'
import { Button } from './button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from './dialog'
import { Input } from './input'
import { Label } from './label'
import { StateBlock } from './state-block'

/** Asks for the scope's token and keeps it in this tab's memory only; the server checks it on every request. */
export function UnlockDialog({ scope, open, onOpenChange }: { scope: Scope; open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useTranslation()
  const id = useId()
  const [value, setValue] = useState('')

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!value.trim()) return
    session.unlock(scope, value)
    setValue('')
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{t(`session.${scope}.title`)}</DialogTitle>
            <DialogDescription>{t(`session.${scope}.description`)}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-1.5">
            <Label htmlFor={id}>{t(`session.${scope}.label`)}</Label>
            <Input
              id={id}
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={value}
              onChange={(event) => setValue(event.target.value)}
            />
            <p className="text-xs text-muted-foreground">{t('session.memoryOnly')}</p>
          </div>
          <DialogFooter>
            <Button type="submit" disabled={!value.trim()}>
              <KeyRound aria-hidden className="size-4" />
              {t('session.unlock')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/** Shows `children` only while the scope is unlocked; otherwise says why and offers the unlock dialog. */
export function RequireUnlock({ scope, children, className }: { scope: Scope; children: ReactNode; className?: string }) {
  const { t } = useTranslation()
  const { unlocked, reason } = useSession(scope)
  const [open, setOpen] = useState(false)
  if (unlocked) return children
  return (
    <>
      <StateBlock
        icon={LockKeyhole}
        title={t(`session.${scope}.lockedTitle`)}
        description={t(reason === 'rejected' ? 'session.rejected' : `session.${scope}.lockedDescription`)}
        className={className}
        action={
          <Button type="button" size="sm" onClick={() => setOpen(true)}>
            <KeyRound aria-hidden className="size-4" />
            {t('session.unlock')}
          </Button>
        }
      />
      <UnlockDialog scope={scope} open={open} onOpenChange={setOpen} />
    </>
  )
}
