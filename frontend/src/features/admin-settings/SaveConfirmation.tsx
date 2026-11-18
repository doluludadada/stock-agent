import { useTranslation } from '@/i18n'
import { ensureAdminResources } from '@/i18n/admin-resources'
import { useSession, type SaveConfirmationProps } from '@/shared/api'
import { ConfirmDialog } from '@/shared/ui/confirm-dialog'
import { useSaveSettings } from './api'
import { startGoogleConfirmation } from './googleConfirmation'
import { refusalOf } from './model'
import { PasswordDialog, type DialogRefusal } from './PasswordDialog'

/**
 * Every save of the settings files, on any page, confirmed the one way the server accepts: the administrator's own
 * password, or for an administrator without one a fresh sign-in with Google made for that save. A wrong password, the
 * attempt limit and a lost connection keep the dialog open.
 */
export function SaveConfirmation({ open, onOpenChange, changes, onSaved, onRefused, title, description, children, ready = true, returnTo, onLeave }: SaveConfirmationProps) {
  ensureAdminResources()
  const { t } = useTranslation('admin')
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
        title={title ?? t('google.title')}
        description={description === undefined ? t('google.description') : `${description} ${t('google.description')}`}
        cancel={t('google.cancel')}
        confirm={t('google.confirm')}
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
