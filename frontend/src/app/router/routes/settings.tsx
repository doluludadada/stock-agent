import { MockAccountPanel } from '@/features/account'
import { MySettingsPage } from '@/features/auth'
import { useShows } from '@/shared/api'

export function MySettingsRoute() {
  const mock = useShows('mock_account')
  return <MySettingsPage mockAccount={mock ? <MockAccountPanel /> : undefined} />
}
