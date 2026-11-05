import { newIndicatorId, newNodeId, type IndicatorTable } from './edit'
import type { Comparison, IdFactory } from './types'

/**
 * Quick fills only populate an ordinary, fully editable comparison. They are starting points;
 * nothing downstream knows which quick fill produced a condition.
 */
export type QuickFillKind = 'maCross' | 'macdCross' | 'rsiThreshold' | 'volumeAboveAverage' | 'volumeAboveYesterday'

export const QUICK_FILLS: readonly QuickFillKind[] = [
  'maCross',
  'macdCross',
  'rsiThreshold',
  'volumeAboveAverage',
  'volumeAboveYesterday',
]

export interface QuickFillResult {
  condition: Comparison
  indicators: IndicatorTable
}

export function quickFill(kind: QuickFillKind, ids: IdFactory): QuickFillResult {
  const id = newNodeId(ids)
  switch (kind) {
    case 'maCross': {
      const fast = newIndicatorId(ids)
      const slow = newIndicatorId(ids)
      return {
        condition: {
          type: 'comparison',
          id,
          operator: 'crosses_above',
          left: { type: 'indicator', indicatorId: fast, output: 'value', barsAgo: 0 },
          right: { type: 'indicator', indicatorId: slow, output: 'value', barsAgo: 0 },
        },
        indicators: { [fast]: { kind: 'sma', period: 20 }, [slow]: { kind: 'sma', period: 60 } } as IndicatorTable,
      }
    }
    case 'macdCross': {
      // Both outputs read the same setting, so the line and its signal can never drift apart.
      const macd = newIndicatorId(ids)
      return {
        condition: {
          type: 'comparison',
          id,
          operator: 'crosses_above',
          left: { type: 'indicator', indicatorId: macd, output: 'line', barsAgo: 0 },
          right: { type: 'indicator', indicatorId: macd, output: 'signal', barsAgo: 0 },
        },
        indicators: { [macd]: { kind: 'macd', fast: 12, slow: 26, signal: 9 } } as IndicatorTable,
      }
    }
    case 'rsiThreshold': {
      const rsi = newIndicatorId(ids)
      return {
        condition: {
          type: 'comparison',
          id,
          operator: 'crosses_above',
          left: { type: 'indicator', indicatorId: rsi, output: 'value', barsAgo: 0 },
          right: { type: 'constant', value: 30 },
        },
        indicators: { [rsi]: { kind: 'rsi', period: 14 } } as IndicatorTable,
      }
    }
    case 'volumeAboveAverage': {
      // The average ends on the previous trading day (barsAgo 1), so today's volume is excluded.
      const average = newIndicatorId(ids)
      return {
        condition: {
          type: 'comparison',
          id,
          operator: 'gt',
          left: { type: 'market', field: 'volume', barsAgo: 0 },
          right: {
            type: 'arithmetic',
            operator: 'multiply',
            left: { type: 'indicator', indicatorId: average, output: 'value', barsAgo: 1 },
            right: { type: 'constant', value: 1.5 },
          },
        },
        indicators: { [average]: { kind: 'volume_sma', period: 20 } } as IndicatorTable,
      }
    }
    case 'volumeAboveYesterday':
      return {
        condition: {
          type: 'comparison',
          id,
          operator: 'gt',
          left: { type: 'market', field: 'volume', barsAgo: 0 },
          right: { type: 'market', field: 'volume', barsAgo: 1 },
        },
        indicators: {},
      }
  }
}
