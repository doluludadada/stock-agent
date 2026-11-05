import type { AccountHistory } from './api'

export type AccountValue = AccountHistory['current']
type Position = AccountValue['positions'][number]

/** A position with what the blotter derives from it. */
export interface Holding extends Position {
  /** Average cost times quantity, as the server reports the cost. */
  cost: number
  /** Unrealized profit or loss over the cost. */
  returnRatio: number
  /** Market value over the account's equity. */
  weight: number
}

/** The positions, largest first. */
export function holdings(value: AccountValue): Holding[] {
  return value.positions
    .map((position) => {
      const cost = position.average_cost * position.quantity
      return { ...position, cost, returnRatio: cost ? position.unrealized_pnl / cost : 0, weight: value.equity ? position.market_value / value.equity : 0 }
    })
    .sort((a, b) => b.market_value - a.market_value)
}

/** Unrealized profit or loss over what the open positions cost; 0 without positions. */
export function unrealizedRatio(value: AccountValue): number {
  const cost = value.positions.reduce((sum, position) => sum + position.average_cost * position.quantity, 0)
  return cost ? value.unrealized_pnl / cost : 0
}

export interface EquityPoint {
  date: string
  value: number
}

/** The daily equity, oldest first. */
export function equityPoints(history: AccountHistory): EquityPoint[] {
  return Object.entries(history.equity_curve)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, value]) => ({ date, value: value.equity }))
}

export interface Move {
  change: number
  ratio: number
}

/** From one point to another; null when there is no earlier point or it was zero. */
export function moveBetween(from: EquityPoint | undefined, to: EquityPoint | undefined): Move | null {
  if (!from || !to || from.value === 0) return null
  return { change: to.value - from.value, ratio: (to.value - from.value) / from.value }
}
