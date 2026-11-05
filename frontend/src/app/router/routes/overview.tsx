import { MarketOverviewPage } from '@/features/market-overview'
import { StrategySummaryPanel } from '@/features/strategies'

export function OverviewRoute() {
  return <MarketOverviewPage strategy={<StrategySummaryPanel />} />
}
