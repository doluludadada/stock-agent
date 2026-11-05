/**
 * Screenshots of every page against a running app and backend, for comparing two versions of the UI.
 *
 *   bun tools/capture-screens.ts <out-dir> [--url http://127.0.0.1:4173] [--token verify-token] [--admin verify-admin-token]
 *
 * Point --url at `vite preview` of a production build whose /v1 reaches a disposable backend. It only reads: it unlocks
 * with the tokens, opens each page and saves a full-page PNG per page, viewport, theme and language. It starts no
 * run, saves nothing and asks for no AI explanation.
 */
import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { chromium, type Page } from '@playwright/test'

interface Options {
  out: string
  url: string
  token: string
  admin: string
}

const VIEWPORTS = { desktop: { width: 1440, height: 900 }, mobile: { width: 390, height: 844 } } as const

const OWNER_PAGES = [
  ['overview', '/'],
  ['stock-2330', '/stocks/2330'],
  ['strategies', '/strategies'],
  ['builder', '/strategies/new?from=balanced'],
  ['runs', '/runs'],
  ['valuation', '/valuation'],
  ['watchlist', '/watchlist'],
  ['account', '/account'],
] as const

interface Variant {
  name: string
  viewport: keyof typeof VIEWPORTS
  theme: 'dark' | 'light'
  locale: 'zh-TW' | 'en'
}

const VARIANTS: Variant[] = [
  { name: 'desktop-dark-zh', viewport: 'desktop', theme: 'dark', locale: 'zh-TW' },
  { name: 'desktop-light-en', viewport: 'desktop', theme: 'light', locale: 'en' },
  { name: 'mobile-dark-zh', viewport: 'mobile', theme: 'dark', locale: 'zh-TW' },
  { name: 'mobile-light-en', viewport: 'mobile', theme: 'light', locale: 'en' },
]

function parseOptions(argv: string[]): Options {
  const out = argv[0]
  if (!out || out.startsWith('--')) throw new Error('usage: bun tools/capture-screens.ts <out-dir> [--url URL] [--token T] [--admin T]')
  const flag = (name: string, fallback: string) => {
    const index = argv.indexOf(`--${name}`)
    return index >= 0 && argv[index + 1] ? argv[index + 1]! : fallback
  }
  return { out: path.resolve(out), url: flag('url', 'http://127.0.0.1:4173'), token: flag('token', 'verify-token'), admin: flag('admin', 'verify-admin-token') }
}

/** Client-side navigation keeps the tokens, which live in the page's memory only. */
async function go(page: Page, to: string) {
  await page.evaluate((target) => {
    window.history.pushState({}, '', target)
    window.dispatchEvent(new PopStateEvent('popstate'))
  }, to)
  await settle(page)
}

async function settle(page: Page) {
  await page.waitForLoadState('networkidle', { timeout: 90_000 }).catch(() => undefined)
  await page.mouse.move(0, 0)
  await page.waitForTimeout(600)
  await page.evaluate(() => window.scrollTo(0, 0))
}

async function unlock(page: Page, scope: 'owner' | 'admin', token: string) {
  const inHeader = page.getByRole('banner').getByRole('button', { name: /解鎖|Unlock/ })
  const inPage = page.getByRole('main').getByRole('button', { name: /解鎖|Unlock/ }).first()
  await (scope === 'owner' && (await inHeader.count()) > 0 ? inHeader : inPage).click()
  await page.getByRole('dialog').locator('input[type="password"]').fill(token)
  await page.getByRole('dialog').getByRole('button', { name: /解鎖|Unlock/ }).click()
  await page.getByRole('dialog').waitFor({ state: 'hidden' })
}

/**
 * A full-page shot taken by growing the viewport to the page's height: Chromium's capture beyond the viewport let
 * Recharts draw past its panel in the image while the page itself was laid out correctly.
 */
async function shoot(page: Page, file: string) {
  const viewport = page.viewportSize()!
  const height = await page.evaluate(() => document.documentElement.scrollHeight)
  await page.setViewportSize({ width: viewport.width, height: Math.max(viewport.height, height) })
  await page.waitForTimeout(400)
  await page.screenshot({ path: file })
  await page.setViewportSize(viewport)
  console.log(file)
}

async function main() {
  const options = parseOptions(process.argv.slice(2))
  mkdirSync(options.out, { recursive: true })
  const browser = await chromium.launch()
  try {
    for (const variant of VARIANTS) {
      const context = await browser.newContext({
        viewport: VIEWPORTS[variant.viewport],
        locale: variant.locale,
        timezoneId: 'Asia/Taipei',
        colorScheme: variant.theme,
        reducedMotion: 'reduce',
      })
      await context.addInitScript(
        ([theme, locale]) => {
          localStorage.setItem('stock-agent.theme', theme!)
          localStorage.setItem('stock-agent.locale', locale!)
        },
        [variant.theme, variant.locale],
      )
      const page = await context.newPage()
      const shot = (name: string) => shoot(page, path.join(options.out, `${variant.name}-${name}.png`))
      await page.goto(options.url)
      await settle(page)
      await shot('overview-locked')
      await unlock(page, 'owner', options.token)
      for (const [name, route] of OWNER_PAGES) {
        await go(page, route)
        await shot(name)
      }
      await go(page, '/admin/settings')
      await unlock(page, 'admin', options.admin)
      await settle(page)
      await shot('admin')
      await go(page, '/no-such-page')
      await shot('not-found')
      await context.close()
    }
  } finally {
    await browser.close()
  }
}

if (import.meta.main) await main()
