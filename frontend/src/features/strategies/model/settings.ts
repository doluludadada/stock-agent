import { LIMITS } from './catalog'
import type { Strategy, StrategyId, StrategySettings } from './types'

/**
 * Changes to the owner's saved settings. Each returns the whole next settings, carrying the revision it started
 * from, because the server replaces the settings as a whole and refuses a stale revision (409).
 */

/** The developer's strategies in config/strategies; an owner strategy may keep one of these ids. */
export const BUILT_IN_IDS = ['conservative', 'balanced', 'aggressive'] as const
export type BuiltInId = (typeof BUILT_IN_IDS)[number]

export function isBuiltInId(id: string): id is BuiltInId {
  return (BUILT_IN_IDS as readonly string[]).includes(id)
}

export type SettingsRefusal = 'selected' | 'last' | 'full'

export function withStrategy(settings: StrategySettings, strategy: Strategy): StrategySettings | SettingsRefusal {
  const exists = settings.strategies.some((item) => item.id === strategy.id)
  if (!exists && settings.strategies.length >= LIMITS.maxStrategies) return 'full'
  const strategies = exists
    ? settings.strategies.map((item) => (item.id === strategy.id ? strategy : item))
    : [...settings.strategies, strategy]
  return { ...settings, strategies }
}

/** A selected strategy cannot go: a workflow would have no strategy. Neither can the last one. */
export function withoutStrategy(settings: StrategySettings, id: StrategyId): StrategySettings | SettingsRefusal {
  if (deletionRefusal(settings, id)) return deletionRefusal(settings, id)!
  return { ...settings, strategies: settings.strategies.filter((item) => item.id !== id) }
}

export function deletionRefusal(settings: StrategySettings, id: StrategyId): SettingsRefusal | null {
  if (settings.activeStrategyId === id || settings.buzzStrategyId === id) return 'selected'
  if (settings.strategies.length <= 1) return 'last'
  return null
}

export function withSelection(settings: StrategySettings, workflow: 'active' | 'buzz', id: StrategyId): StrategySettings {
  return workflow === 'active' ? { ...settings, activeStrategyId: id } : { ...settings, buzzStrategyId: id }
}

export function isRefusal(value: StrategySettings | SettingsRefusal): value is SettingsRefusal {
  return typeof value === 'string'
}
