import enAccount from './locales/en/account'
import enAdmin from './locales/en/admin'
import enAuth from './locales/en/auth'
import enBuilder from './locales/en/builder'
import enCommon from './locales/en/common'
import enFormula from './locales/en/formula'
import enOverview from './locales/en/overview'
import enResearch from './locales/en/research'
import enRuns from './locales/en/runs'
import enValuation from './locales/en/valuation'
import enStrategies from './locales/en/strategies'
import enWatchlist from './locales/en/watchlist'
import zhAccount from './locales/zh-TW/account'
import zhAdmin from './locales/zh-TW/admin'
import zhAuth from './locales/zh-TW/auth'
import zhBuilder from './locales/zh-TW/builder'
import zhCommon from './locales/zh-TW/common'
import zhFormula from './locales/zh-TW/formula'
import zhOverview from './locales/zh-TW/overview'
import zhResearch from './locales/zh-TW/research'
import zhRuns from './locales/zh-TW/runs'
import zhValuation from './locales/zh-TW/valuation'
import zhStrategies from './locales/zh-TW/strategies'
import zhWatchlist from './locales/zh-TW/watchlist'

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
    valuation: enValuation,
    account: enAccount,
    admin: enAdmin,
    auth: enAuth,
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
    valuation: zhValuation,
    account: zhAccount,
    admin: zhAdmin,
    auth: zhAuth,
  },
} as const

export type Namespace = keyof (typeof resources)['en']
export const NAMESPACES = Object.keys(resources.en) as Namespace[]
