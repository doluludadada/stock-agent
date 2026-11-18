import { useTranslation } from '@/i18n'
import type { Broker, Server } from './brokers'

/** Whether an account is a real broker's, whose login is on Simulation or on Production. */
export const REAL_BROKER: Readonly<Record<Broker, boolean>> = { mock: false, shioaji: true }

/** Whether an order on a real broker's login on the server is real money. */
export const REAL_MONEY: Readonly<Record<Server, boolean>> = { simulation: false, production: true }

/**
 * An account as the site names it: the site's own mock account, or a real broker's account with the server the site's
 * login on it is on, so the two are never taken for each other. `server` is null where the site holds no login.
 */
export function useAccountLabel() {
  const { t } = useTranslation('common')
  return (broker: Broker, server: Server | null) => {
    const name = t(`broker.name.${broker}`)
    if (!REAL_BROKER[broker] || server === null) return name
    return t('broker.withServer', { name, server: t(`broker.server.${server}`) })
  }
}
