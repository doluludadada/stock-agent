import { BrokerageAccountPage } from '@/features/account'
import { SaveConfirmation } from '@/features/admin-settings'

/** The SinoPac account, managed through the settings save's own confirmation. */
export function BrokerageRoute() {
  return <BrokerageAccountPage Confirmation={SaveConfirmation} />
}
