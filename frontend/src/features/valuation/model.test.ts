import openapi from '@/shared/api/openapi.json'
import { MIN_UNDERVALUATION_MAX, parseMinUndervaluation, parseTargetPe, TARGET_PE_MAX } from './model'

type Parameter = { name: string; schema: { maximum?: number; exclusiveMinimum?: number; minimum?: number } }
const scan = (openapi.paths as unknown as Record<string, { get: { parameters: Parameter[] } }>)['/v1/valuation/scan']!.get.parameters

describe('valuation inputs', () => {
  it('use the bounds of the scan endpoint', () => {
    expect(TARGET_PE_MAX).toBe(scan.find((item) => item.name === 'target_pe')!.schema.maximum)
    expect(MIN_UNDERVALUATION_MAX).toBe(scan.find((item) => item.name === 'min_undervaluation')!.schema.maximum)
  })

  it('take a target P/E above 0 up to the bound', () => {
    expect(parseTargetPe('15')).toBe(15)
    expect(parseTargetPe('1000')).toBe(1000)
    expect(parseTargetPe('0')).toBeNull()
    expect(parseTargetPe('1000.5')).toBeNull()
    expect(parseTargetPe('')).toBeNull()
    expect(parseTargetPe('abc')).toBeNull()
  })

  it('read a minimum undervaluation typed in percent', () => {
    expect(parseMinUndervaluation('30')).toBeCloseTo(0.3)
    expect(parseMinUndervaluation('0')).toBe(0)
    expect(parseMinUndervaluation('')).toBeNull()
    expect(parseMinUndervaluation('-1')).toBeNull()
  })
})
