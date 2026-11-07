import { Navigate, useLocation } from 'react-router'
import { MarketOverviewPage } from '@/features/market-overview'
import { StrategySummaryPanel } from '@/features/strategies'
import { paths } from '@/shared/config/paths'

export function OverviewRoute() {
  return <MarketOverviewPage strategy={<StrategySummaryPanel />} />
}

/** The market overview's address before it became the home page; old links, `?target=` included, still arrive. */
export function MarketRedirect() {
  const { search } = useLocation()
  return <Navigate to={{ pathname: paths.market, search }} replace />
}
