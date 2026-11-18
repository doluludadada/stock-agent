import { MockAccountPanel } from '@/features/account'
import { MySettingsPage } from '@/features/auth'
import { FollowSettingsPanel } from '@/features/ranking'
import { useShows } from '@/shared/api'

/** My settings, with the mock account's panel where the site shows it and the ranking follow's where it shows the ranking. */
export function MySettingsRoute() {
  const mock = useShows('mock_account')
  const ranking = useShows('ranking')
  const panels =
    mock || ranking ? (
      <>
        {mock && <MockAccountPanel />}
        {ranking && <FollowSettingsPanel />}
      </>
    ) : undefined
  return <MySettingsPage accountPanels={panels} />
}
