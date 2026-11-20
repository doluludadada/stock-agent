import { useQuery } from '@tanstack/react-query'
import { useShows } from './features'
import { apiRequest } from './http'
import { SITE_STATE_STALE_MS } from './query-keys'
import type { components } from './schema.gen'
import { useIsSignedIn } from './session'

type Schemas = components['schemas']

/** Whose account a run orders on: the user's mock account, or a real broker. */
export type Broker = Schemas['ExecutionProvider']

/** The server a real broker's login is on: SinoPac's Simulation, no real money, or Production, real money. */
export type Server = Schemas['ShioajiServer']

/**
 * A broker the user may choose now. A real one carries what a confirmation names: its server and its BUY limits, shares
 * of the account's equity as each run values it: one BUY's, and the day's BUYs'.
 */
export type BrokerOffer =
  | { broker: 'mock' }
  | { broker: Exclude<Broker, 'mock'>; server: Server; max_order_equity_pct: number; max_daily_buy_equity_pct: number }

/**
 * The query of a start that orders on `offer`: the broker, and for a real one the server its confirmation showed. The
 * server refuses the start (broker_server_changed) when its login is on another server by then.
 */
export function brokerQuery(offer: BrokerOffer): { broker: Broker; server?: Server } {
  return offer.broker === 'mock' ? { broker: offer.broker } : { broker: offer.broker, server: offer.server }
}

const MOCK_ONLY: readonly BrokerOffer[] = [{ broker: 'mock' }]
const NONE: readonly BrokerOffer[] = []

export const brokersKey = ['owner', 'brokers'] as const

/**
 * The chosen broker's offer while it is still offered, else the mock account: a choice never outlives the broker's
 * login, and a real broker is never chosen for the user, even where the site shows no other.
 */
export function chosenOffer(offers: readonly BrokerOffer[], chosen: Broker): BrokerOffer {
  return offers.find((offer) => offer.broker === chosen) ?? { broker: 'mock' }
}

/** A real broker sent without its server or its limits is left out: no confirmation could name them. */
function offerOf({ broker, server, max_order_equity_pct, max_daily_buy_equity_pct }: Schemas['BrokerResponse']): BrokerOffer[] {
  if (broker === 'mock') return [{ broker }]
  if (server === null || max_order_equity_pct === null || max_daily_buy_equity_pct === null) return []
  return [{ broker, server, max_order_equity_pct, max_daily_buy_equity_pct }]
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
    staleTime: SITE_STATE_STALE_MS,
    refetchOnWindowFocus: true,
  })
}

/**
 * The brokers to offer now: the server's list, which leaves out a broker whose feature the site hides, and until it
 * answers the mock account alone where the site shows that. Empty where the viewer may use no account.
 */
export function useBrokerOffers(): readonly BrokerOffer[] {
  const mock = useShows('mock_account')
  return useBrokers().data ?? (mock ? MOCK_ONLY : NONE)
}
