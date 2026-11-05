import { AdminSettingsPage } from '@/features/admin-settings'

/** The server checks ADMIN_API_TOKEN on every request; this route only shows the page. */
export function AdminSettingsRoute() {
  return <AdminSettingsPage />
}
