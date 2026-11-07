import { useQuery } from '@tanstack/react-query'
import { apiRequest } from './http'
import type { components } from './schema.gen'
import { useIsSignedIn } from './session'

type Schemas = components['schemas']

/** Whose account a run orders on: the user's mock account, or a real broker. */
export type Broker = Schemas['ExecutionProvider']

/** A broker the user may choose now. A real one carries what a confirmation names: its server and its BUY limits. */
export type BrokerOffer =
  | { broker: 'mock' }
  | { broker: Exclude<Broker, 'mock'>; simulation: boolean; max_order_value: number; max_daily_buy_value: number }

/** What a user is offered until the server has said more, and on every site without a broker login. */
export const MOCK_ONLY: readonly BrokerOffer[] = [{ broker: 'mock' }]

export const brokersKey = ['owner', 'brokers'] as const

/** The chosen broker's offer while it is still offered, else the mock account: a choice never outlives the broker's login. */
export function chosenOffer(offers: readonly BrokerOffer[], chosen: Broker): BrokerOffer {
  return offers.find((offer) => offer.broker === chosen) ?? { broker: 'mock' }
}

/** A real broker sent without its server or its limits is left out: no confirmation could name them. */
function offerOf({ broker, simulation, max_order_value, max_daily_buy_value }: Schemas['BrokerResponse']): BrokerOffer[] {
  if (broker === 'mock') return [{ broker }]
  if (simulation === null || max_order_value === null || max_daily_buy_value === null) return []
  return [{ broker, simulation, max_order_value, max_daily_buy_value }]
}

/**
 * The brokers the signed-in user may choose now, the mock account first. A real broker needs the site's login, which
 * can go down and come back while the tab stays open, so the list is asked again like the audience.
 */
export function useBrokers() {
  const signedIn = useIsSignedIn()
  return useQuery({
    queryKey: brokersKey,
    queryFn: async ({ signal }) => (await apiRequest('get', '/v1/account/brokers', { signal })).flatMap(offerOf),
    enabled: signedIn,
    staleTime: 60_000,
    refetchOnWindowFocus: true,
  })
}
