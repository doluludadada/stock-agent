import type { User } from '@/shared/api'

/** A signed-in user of the role user, as GET /v1/auth/me answers, for tests that need a session. */
export const TEST_USER: User = {
  user_id: 'u-mei',
  username: 'mei',
  email: 'mei@example.com',
  role: 'user',
  status: 'active',
  permissions: [],
  created_at: '2026-11-04T01:00:00Z',
}

/** The first administrator, with the permissions the server lists for the role. */
export const TEST_ADMIN: User = {
  user_id: 'local',
  username: 'hsiu',
  email: 'hsiu@example.com',
  role: 'administrator',
  status: 'active',
  permissions: ['manage_users', 'edit_system_settings', 'use_cli', 'notify_recipients', 'uncapped_ai'],
  created_at: '2026-11-04T00:00:00Z',
}
