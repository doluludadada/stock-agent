import enAccount from './locales/en/account'
import enAttribution from './locales/en/attribution'
import enAuth from './locales/en/auth'
import enBacktest from './locales/en/backtest'
import enBuilder from './locales/en/builder'
import enCommon from './locales/en/common'
import enFormula from './locales/en/formula'
import enHoldings from './locales/en/holdings'
import enOverview from './locales/en/overview'
import enRanking from './locales/en/ranking'
import enResearch from './locales/en/research'
import enRuns from './locales/en/runs'
import enValuation from './locales/en/valuation'
import enStrategies from './locales/en/strategies'
import enWatchlist from './locales/en/watchlist'
import zhAccount from './locales/zh-TW/account'
import zhAttribution from './locales/zh-TW/attribution'
import zhAuth from './locales/zh-TW/auth'
import zhBacktest from './locales/zh-TW/backtest'
import zhBuilder from './locales/zh-TW/builder'
import zhCommon from './locales/zh-TW/common'
import zhFormula from './locales/zh-TW/formula'
import zhHoldings from './locales/zh-TW/holdings'
import zhOverview from './locales/zh-TW/overview'
import zhRanking from './locales/zh-TW/ranking'
import zhResearch from './locales/zh-TW/research'
import zhRuns from './locales/zh-TW/runs'
import zhValuation from './locales/zh-TW/valuation'
import zhStrategies from './locales/zh-TW/strategies'
import zhWatchlist from './locales/zh-TW/watchlist'

/** The words every page may need. The settings form's are apart, in admin-resources.ts, and load with its page. */
export const resources = {
  en: {
    common: enCommon,
    overview: enOverview,
    strategies: enStrategies,
    formula: enFormula,
    builder: enBuilder,
    watchlist: enWatchlist,
    research: enResearch,
    runs: enRuns,
    backtest: enBacktest,
    ranking: enRanking,
    valuation: enValuation,
    account: enAccount,
    holdings: enHoldings,
    auth: enAuth,
    attribution: enAttribution,
  },
  'zh-TW': {
    common: zhCommon,
    overview: zhOverview,
    strategies: zhStrategies,
    formula: zhFormula,
    builder: zhBuilder,
    watchlist: zhWatchlist,
    research: zhResearch,
    runs: zhRuns,
    backtest: zhBacktest,
    ranking: zhRanking,
    valuation: zhValuation,
    account: zhAccount,
    holdings: zhHoldings,
    auth: zhAuth,
    attribution: zhAttribution,
  },
} as const

export type Namespace = keyof (typeof resources)['en']
export const NAMESPACES = Object.keys(resources.en) as Namespace[]
