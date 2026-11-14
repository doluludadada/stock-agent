import type { Audience } from '@/shared/api'

/** GET /v1/market/audience of the owner's own site, which allows every workflow. */
export const PERSONAL_SITE: Audience = { audience: 'personal', open_data_only: false, realtime_quotes: true, news_articles: true, mops: true, annual_reports: true, order_pricing: 'realtime_quote' }

/** The same answer of a public site on open data only. */
export const PUBLIC_SITE: Audience = { audience: 'public', open_data_only: true, realtime_quotes: false, news_articles: false, mops: false, annual_reports: false, order_pricing: 'official_close' }
