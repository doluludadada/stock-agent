import { MockAccountPanel } from '@/features/account'
import { MySettingsPage } from '@/features/auth'
import { FollowSchedulePanel } from '@/features/ranking'
import { useShows } from '@/shared/api'

export function MySettingsRoute() {
  const mock = useShows('mock_account')
  const ranking = useShows('ranking')
  const panels = mock ? (
    <>
      <MockAccountPanel />
      {ranking && <FollowSchedulePanel />}
    </>
  ) : undefined
  return <MySettingsPage mockAccount={panels} />
}
