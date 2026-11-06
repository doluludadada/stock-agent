import { MockAccountPanel } from '@/features/account'
import { MySettingsPage } from '@/features/auth'

export function MySettingsRoute() {
  return <MySettingsPage mockAccount={<MockAccountPanel />} />
}
