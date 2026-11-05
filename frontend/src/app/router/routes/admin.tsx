import { AdminSettingsPage } from '@/features/admin-settings'

/** The server checks the signed-in user's permission on every request; this route only shows the page. */
export function AdminSettingsRoute() {
  return <AdminSettingsPage />
}
