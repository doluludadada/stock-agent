import { useTranslation } from '@/i18n'
import { PageHeader } from '@/shared/ui/page-header'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { SettingsForm } from './SettingsForm'

/** The administrator's settings: every setting as a form field, applied at once on save. */
export function AdminSettingsPage() {
  const { t } = useTranslation('admin')
  return (
    <div className="space-y-5">
      <PageHeader eyebrow={t('common:nav.section.admin')} title={t('title')} description={t('description')} />
      <RequireSignIn needs="edit_system_settings" layout="page" reason={t('signIn')}>
        <SettingsForm />
      </RequireSignIn>
    </div>
  )
}
