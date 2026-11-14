import { useTranslation } from '@/i18n'
import { ensureAdminResources } from '@/i18n/admin-resources'
import { PageHeader } from '@/shared/ui/page-header'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { SettingsForm } from './SettingsForm'

/** The administrator's settings: every setting as a form field, applied at once on save. */
export function AdminSettingsPage() {
  ensureAdminResources()
  const { t } = useTranslation('admin')
  return (
    <div className="page-stack">
      <PageHeader title={t('title')} description={t('description')} />
      <RequireSignIn needs="edit_system_settings" layout="page" reason={t('signIn')}>
        <SettingsForm />
      </RequireSignIn>
    </div>
  )
}
