import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest, isSameSession, sentInSession, strategyResultsKey, useIsSignedIn, type Schemas } from '@/shared/api'

export type StockTechnical = Schemas['StockTechnicalResponse']
export type StockFinancials = Schemas['StockFinancialsResponse']

/** Daily history settles once a day; a minute keeps repeated visits from recomputing. */
const TECHNICAL_STALE_MS = 60_000

export const technicalKey = (stockId: string) => [...strategyResultsKey, 'technical', stockId] as const

/** The owner's active strategy on this stock, computed by the backend exactly as a run computes it. */
export function useStockTechnical(stockId: string) {
  const signedIn = useIsSignedIn()
  return useQuery({
    queryKey: technicalKey(stockId),
    queryFn: ({ signal }) => apiRequest('get', '/v1/market/stocks/{stock_id}/technical', { params: { stock_id: stockId }, signal }),
    enabled: signedIn,
    staleTime: TECHNICAL_STALE_MS,
  })
}

/** The archive gains a quarter or a month a few times a month; ten minutes keeps repeated visits from asking again. */
const FINANCIALS_STALE_MS = 10 * 60_000

/** The stock's archived quarters and monthly revenue, from the exchanges' open data. Public. */
export function useStockFinancials(stockId: string) {
  return useQuery({
    queryKey: ['public', 'market', 'financials', stockId] as const,
    queryFn: ({ signal }) => apiRequest('get', '/v1/market/stocks/{stock_id}/financials', { params: { stock_id: stockId }, signal }),
    staleTime: FINANCIALS_STALE_MS,
  })
}

export type StockAnalysis = Schemas['StockAnalysis']
export type StockNews = Schemas['StockNewsResponse']
export type StockRanking = Schemas['StockRankingResponse']

/** The analysis reads held data only, which gains a month, a quarter or a session at most once a day. */
export function useStockAnalysis(stockId: string) {
  return useQuery({
    queryKey: ['public', 'market', 'analysis', stockId] as const,
    queryFn: ({ signal }) => apiRequest('get', '/v1/market/stocks/{stock_id}/analysis', { params: { stock_id: stockId }, signal }),
    staleTime: FINANCIALS_STALE_MS,
  })
}

/** The server holds a stock's fetched news for its own freshness window; five minutes keeps a revisit from asking it again. */
const NEWS_STALE_MS = 5 * 60_000

/**
 * What is said about the stock: announcements, exchange news and, where the site may read them, articles and posts.
 * Private: the server asks a news site or the board only for a signed-in viewer.
 */
export function useStockNews(stockId: string) {
  const signedIn = useIsSignedIn()
  return useQuery({
    queryKey: ['owner', 'market', 'news', stockId] as const,
    queryFn: ({ signal }) => apiRequest('get', '/v1/market/stocks/{stock_id}/news', { params: { stock_id: stockId }, signal }),
    enabled: signedIn,
    staleTime: NEWS_STALE_MS,
  })
}

/**
 * The stock's score: where it stands in the monthly ranking. Public. The first answer after a server start reads
 * every held bar, so it can take a while; a refusal (no decision session yet) is an answer and is not retried.
 */
export function useStockRanking(stockId: string) {
  return useQuery({
    queryKey: ['public', 'market', 'ranking', stockId] as const,
    queryFn: ({ signal }) => apiRequest('get', '/v1/market/stocks/{stock_id}/ranking', { params: { stock_id: stockId }, signal }),
    staleTime: FINANCIALS_STALE_MS,
    retry: false,
  })
}

/** A brief being written is asked for again this often, until the AI has answered. */
export const BRIEF_POLL_MS = 3_000

export const companyKey = (stockId: string) => ['public', 'market', 'company', stockId] as const

/**
 * What the site holds about the stock's company: its profile, its sources and its card, with no fetch and no AI call.
 * Public. While a brief is being written (`writing`) it is asked again as often as the brief, since that request
 * reads the company's filings and writes its card first: the page says how far it has come, and the card shows once
 * it is written.
 */
export function useStockCompany(stockId: string, writing = false) {
  return useQuery({
    queryKey: companyKey(stockId),
    queryFn: ({ signal }) => apiRequest('get', '/v1/market/stocks/{stock_id}/company', { params: { stock_id: stockId }, signal }),
    staleTime: FINANCIALS_STALE_MS,
    refetchInterval: writing ? BRIEF_POLL_MS : false,
  })
}

/** A brief changes when a viewer asks for one; a minute keeps a revisit from asking the server again. */
const BRIEF_STALE_MS = 60_000

export const briefKey = (stockId: string) => ['public', 'market', 'brief', stockId] as const

/** The AI brief the site holds of the stock, with no AI call. Public. It polls only while today's is being written. */
export function useStockBrief(stockId: string) {
  return useQuery({
    queryKey: briefKey(stockId),
    queryFn: ({ signal }) => apiRequest('get', '/v1/market/stocks/{stock_id}/brief', { params: { stock_id: stockId }, signal }),
    staleTime: BRIEF_STALE_MS,
    refetchInterval: (query) => (query.state.data?.today?.status === 'writing' ? BRIEF_POLL_MS : false),
  })
}

/**
 * One paid AI call per click, never made by a render: the server writes one brief per stock and day for every viewer
 * and waits for the AI before it answers. The same request first reads the company's filings where they are due and
 * writes its card when it has none, which can take a minute, so the card is read again after it. A refusal reloads
 * what the site holds, since another viewer may hold the claim.
 */
export function useWriteStockBrief(stockId: string) {
  const client = useQueryClient()
  const key = briefKey(stockId)
  return useMutation({
    mutationFn: () => apiRequest('post', '/v1/market/stocks/{stock_id}/brief', { params: { stock_id: stockId }, body: { confirm: true } }),
    onMutate: sentInSession,
    onSuccess: (answer, _nothing, sent) => {
      if (isSameSession(sent)) client.setQueryData(key, answer)
      void client.invalidateQueries({ queryKey: companyKey(stockId) })
    },
    onError: () => client.invalidateQueries({ queryKey: key }),
  })
}
