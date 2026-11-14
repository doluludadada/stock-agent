/**
 * Query keys start with their scope ('public', 'owner' or 'admin'), so a scope's cache can be dropped as a whole.
 * Answers the backend computes with the owner's saved technical strategy also start with this key: saving or
 * switching a strategy drops all of them, so no page shows a result of the strategy that was replaced.
 */
export const strategyResultsKey = ['owner', 'strategy-results'] as const

/** What a workflow run changes, the mock account and the watchlist, starts with this key: a run's end reloads them. */
export const runResultsKey = ['owner', 'run-results'] as const

/**
 * How long what the site says about itself and the viewer (the audience, the features it shows, the brokers it offers,
 * who is signed in) counts as fresh. Each can change while a tab stays open, so the tab asks again when it is back in
 * focus after this long.
 */
export const SITE_STATE_STALE_MS = 60_000
