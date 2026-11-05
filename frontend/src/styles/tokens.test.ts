import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * WCAG 2 contrast of the palette in tokens.css, for both themes: every text role on every surface it is drawn on.
 * Colors are oklch(L C H [/ alpha]); a translucent tint is composited over the panel surface the way the browser
 * paints it.
 */

type Rgb = [number, number, number]
interface Color {
  l: number
  c: number
  h: number
  alpha: number
}

const css = readFileSync(path.resolve(import.meta.dirname, 'tokens.css'), 'utf8')

function block(selector: ':root' | '.dark'): Record<string, Color> {
  const blocks = [...css.matchAll(/(^|\n)(:root|\.dark) \{([^}]*)\}/g)].filter((match) => match[2] === selector && match[3]!.includes('--palette-canvas'))
  expect(blocks, `${selector} palette block`).toHaveLength(1)
  const colors: Record<string, Color> = {}
  for (const [, name, l, c, h, alpha] of blocks[0]![3]!.matchAll(/--palette-([\w-]+):\s*oklch\(([\d.]+) ([\d.]+) ([\d.]+)(?: \/ ([\d.]+)%)?\)/g)) {
    colors[name!] = { l: Number(l), c: Number(c), h: Number(h), alpha: alpha === undefined ? 1 : Number(alpha) / 100 }
  }
  return colors
}

function srgb({ l, c, h }: Color): Rgb {
  const a = c * Math.cos((h * Math.PI) / 180)
  const b = c * Math.sin((h * Math.PI) / 180)
  const lms = [l + 0.3963377774 * a + 0.2158037573 * b, l - 0.1055613458 * a - 0.0638541728 * b, l - 0.0894841775 * a - 1.291485548 * b].map((v) => v ** 3)
  const [L, M, S] = lms as Rgb
  const linear: Rgb = [
    4.0767416621 * L - 3.3077115913 * M + 0.2309699292 * S,
    -1.2684380046 * L + 2.6097574011 * M - 0.3413193965 * S,
    -0.0041960863 * L - 0.7034186147 * M + 1.707614701 * S,
  ]
  return linear.map((v) => {
    const clamped = Math.min(1, Math.max(0, v))
    return clamped <= 0.0031308 ? 12.92 * clamped : 1.055 * clamped ** (1 / 2.4) - 0.055
  }) as Rgb
}

function over(top: Color, below: Color, alpha = top.alpha): Rgb {
  const [front, back] = [srgb(top), srgb(below)]
  return front.map((value, index) => value * alpha + back[index]! * (1 - alpha)) as Rgb
}

function luminance(rgb: Rgb): number {
  const [r, g, b] = rgb.map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)) as Rgb
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function contrast(a: Rgb, b: Rgb): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number]
  return (light + 0.05) / (dark + 0.05)
}

const TEXT_ROLES = ['ink', 'ink-muted', 'ink-faint', 'brand', 'market-up', 'market-down', 'market-flat', 'gold', 'warning', 'danger'] as const
const SURFACES = ['canvas', 'surface', 'surface-raised', 'surface-sunken'] as const
/** Text drawn on a tint: the tint over the panel surface. */
const ON_TINTS = [
  ['ink', 'market-up-soft'],
  ['ink', 'market-down-soft'],
  ['market-up', 'market-up-soft'],
  ['market-down', 'market-down-soft'],
  ['brand', 'brand-soft'],
  ['gold', 'gold-soft'],
  ['danger', 'danger-soft'],
  // The settings editor's line diff, its notices and a problem underlined in the text.
  ['ink', 'brand-soft'],
  ['ink', 'gold-soft'],
  ['ink', 'danger-soft'],
] as const
/** The strongest heat-map tile is the market color at this share over the panel; its text is ink. */
const STRONGEST_HEAT = 0.4

describe.each([
  ['light', ':root'],
  ['dark', '.dark'],
] as const)('the %s palette', (_theme, selector) => {
  const palette = block(selector)
  const solid = (name: string) => {
    expect(palette[name], `--palette-${name}`).toBeDefined()
    return srgb(palette[name]!)
  }

  it.each(TEXT_ROLES)('draws %s text at 4.5:1 or more on every surface', (role) => {
    for (const surface of SURFACES) expect(contrast(solid(role), solid(surface)), `${role} on ${surface}`).toBeGreaterThanOrEqual(4.5)
  })

  it('draws text on brand buttons and on tints at 4.5:1 or more', () => {
    expect(contrast(solid('on-brand'), solid('brand'))).toBeGreaterThanOrEqual(4.5)
    for (const [text, tint] of ON_TINTS) {
      expect(contrast(solid(text), over(palette[tint]!, palette.surface!)), `${text} on ${tint}`).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('keeps ink readable on the strongest heat-map tile', () => {
    for (const market of ['market-up', 'market-down']) {
      expect(contrast(solid('ink'), over(palette[market]!, palette.surface!, STRONGEST_HEAT)), market).toBeGreaterThanOrEqual(4.5)
    }
  })
})
