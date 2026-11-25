import type { ReactNode } from 'react'
import { useTranslation } from '@/i18n'
import { refusalOf, startGoogleConfirmation, useSaveSettings, useSession, type PageRefusal, type Schemas } from '@/shared/api'
import { ConfirmDialog } from '@/shared/ui/confirm-dialog'
import { PasswordDialog, type DialogRefusal } from '@/shared/ui/password-dialog'

interface SaveConfirmationProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  changes: Schemas['SettingChange'][]
  onSaved: () => void
  onRefused: (refusal: PageRefusal) => void
  /** A page's own title and sentence, in place of the settings page's. */
  title?: string
  description?: string
  /** What the dialog shows before it asks: what the save changes, and a field of the page's own. */
  children?: ReactNode
  /** False holds the confirmation until the page's own field is filled. */
  ready?: boolean
  /**
   * The page the save is made on when it is not the settings page. Google sends the browser back to the settings
   * page, which sends the save and then goes back here.
   */
  returnTo?: string
  /** Called right before the browser leaves for Google, so the page lets it go without asking. */
  onLeave?: () => void
}

/**
 * Every save of the settings files, on any page, confirmed the one way the server accepts: the administrator's own
 * password, or for an administrator without one a fresh sign-in with Google made for that save. A wrong password, the
 * attempt limit and a lost connection keep the dialog open.
 */
export function SaveConfirmation({ open, onOpenChange, changes, onSaved, onRefused, title, description, children, ready = true, returnTo, onLeave }: SaveConfirmationProps) {
  const { t } = useTranslation()
  const session = useSession()
  const save = useSaveSettings()
  const byGoogle = session.status === 'signedIn' && !session.user.has_password

  const confirm = async (password: string): Promise<DialogRefusal | null> => {
    try {
      await save.mutateAsync({ changes, password })
      onSaved()
      return null
    } catch (error) {
      const refusal = refusalOf(error)
      if (refusal.kind === 'refused' || refusal.kind === 'conflict') onRefused(refusal)
      else if (refusal.kind === 'googleRequired') return { kind: 'failed', error }
      else return refusal
      return null
    }
  }

  if (byGoogle) {
    return (
      <ConfirmDialog
        open={open}
        onOpenChange={onOpenChange}
        title={title ?? t('settingsSave.google.title')}
        description={description === undefined ? t('settingsSave.google.description') : `${description} ${t('settingsSave.google.description')}`}
        cancel={t('settingsSave.google.cancel')}
        confirm={t('settingsSave.google.confirm')}
        confirmDisabled={!ready}
        onConfirm={() => {
          onLeave?.()
          startGoogleConfirmation({ changes, returnTo })
        }}
      >
        {children}
      </ConfirmDialog>
    )
  }
  return (
    <PasswordDialog open={open} onOpenChange={onOpenChange} onConfirm={confirm} title={title} description={description} ready={ready}>
      {children}
    </PasswordDialog>
  )
}
