/**
 * Screenshots of every page against a running app and backend, at 375, 768, 1024 and 1440 px in both themes, and an
 * audit of each: horizontal page scroll, controls under 44 px on a phone, text cut off, and page errors.
 *
 *   bun tools/capture-screens.ts <out-dir> [--url http://127.0.0.1:4173] [--user name --password pw]
 *     [--member name --member-password pw] [--only overview,watchlist] [--widths 375,1440] [--themes light]
 *
 * Point --url at the dev server or `vite preview` of a build whose /v1 reaches a disposable backend that already has
 * accounts. It signs in through the API (the server sets the session cookie) and otherwise only reads: it starts no
 * run, saves nothing and asks for no AI explanation. Each shot is `<page>-<width>-<theme>.png`; `audit.json` lists
 * what each shot's audit found, and the run exits 1 when any shot scrolls sideways or has a small phone control.
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { chromium, type Browser, type Page } from '@playwright/test'

interface Options {
  out: string
  url: string
  user: string
  password: string
  member: string | null
  memberPassword: string | null
  only: Set<string> | null
  widths: number[]
  themes: Theme[]
}

type Theme = 'light' | 'dark'
type Session = 'signedOut' | 'admin' | 'member'

interface Shot {
  name: string
  path: string
  session: Session
  /** Prepares the page after it loads: opens a menu, fills a form. */
  prepare?: (page: Page) => Promise<void>
  /** Shoots the viewport only, for a menu or a sheet over the page. */
  viewportOnly?: boolean
  phoneOnly?: boolean
}

interface Finding {
  shot: string
  overflow: number
  smallTargets: string[]
  clipped: string[]
  errors: string[]
}

const HEIGHTS: Record<number, number> = { 375: 812, 768: 1024, 1024: 768, 1440: 900 }

function parseOptions(argv: string[]): Options {
  const out = argv[0]
  if (!out || out.startsWith('--')) throw new Error('usage: bun tools/capture-screens.ts <out-dir> [--url URL] [--user NAME --password PW] [--only a,b]')
  const flag = (name: string) => {
    const index = argv.indexOf(`--${name}`)
    return index >= 0 ? (argv[index + 1] ?? null) : null
  }
  const list = (name: string) => flag(name)?.split(',').filter(Boolean) ?? null
  return {
    out: path.resolve(out),
    url: flag('url') ?? 'http://127.0.0.1:4173',
    user: flag('user') ?? 'e2e-admin',
    password: flag('password') ?? 'e2e administrator pass',
    member: flag('member'),
    memberPassword: flag('member-password'),
    only: list('only') ? new Set(list('only')) : null,
    widths: (list('widths') ?? ['375', '768', '1024', '1440']).map(Number),
    themes: (list('themes') ?? ['light', 'dark']) as Theme[],
  }
}

const openAccountMenu = async (page: Page) => {
  await page.getByRole('banner').getByRole('button', { name: /的帳號選單|Account menu/ }).click()
  await page.getByRole('menu').waitFor()
}

function shots(runId: string | null, needsSetup: boolean): Shot[] {
  if (needsSetup) return [{ name: 'setup', path: '/setup', session: 'signedOut' }]
  return [
    { name: 'sign-in', path: '/sign-in?next=%2Fwatchlist', session: 'signedOut' },
    { name: 'register', path: '/register', session: 'signedOut' },
    { name: 'runs-signed-out', path: '/', session: 'signedOut' },
    { name: 'overview-signed-out', path: '/market', session: 'signedOut' },
    { name: 'watchlist-signed-out', path: '/watchlist', session: 'signedOut' },
    { name: 'overview', path: '/market', session: 'admin' },
    { name: 'stock-2330', path: '/stocks/2330', session: 'admin' },
    { name: 'watchlist', path: '/watchlist', session: 'admin' },
    { name: 'account', path: '/account', session: 'admin' },
    { name: 'my-settings', path: '/settings', session: 'admin' },
    { name: 'strategies', path: '/strategies', session: 'admin' },
    { name: 'builder', path: '/strategies/new?builtin=balanced', session: 'admin' },
    { name: 'runs', path: '/', session: 'admin' },
    ...(runId ? [{ name: 'run-detail', path: `/runs/${runId}`, session: 'admin' as const }] : []),
    { name: 'valuation', path: '/valuation', session: 'admin' },
    { name: 'users', path: '/admin/users', session: 'admin' },
    { name: 'admin-settings', path: '/admin/settings', session: 'admin' },
    { name: 'user-menu', path: '/', session: 'admin', prepare: openAccountMenu, viewportOnly: true },
    {
      name: 'more-sheet',
      path: '/',
      session: 'admin',
      phoneOnly: true,
      viewportOnly: true,
      prepare: async (page) => {
        await page.getByRole('button', { name: /^(更多|More)$/ }).click()
        await page.getByRole('dialog').waitFor()
      },
    },
    { name: 'users-as-member', path: '/admin/users', session: 'member' },
    { name: 'not-found', path: '/no-such-page', session: 'admin' },
  ]
}

async function settle(page: Page) {
  await page.waitForLoadState('networkidle', { timeout: 90_000 }).catch(() => undefined)
  await page
    .waitForFunction(() => document.querySelectorAll('[data-slot="skeleton"]').length === 0, undefined, { timeout: 30_000 })
    .catch(() => undefined)
  await page.mouse.move(0, 0)
  await page.waitForTimeout(500)
}

/** Measures what a reader would notice: sideways scroll, small phone controls, and text cut off without a way to read it. */
async function audit(page: Page, width: number): Promise<Omit<Finding, 'shot' | 'errors'>> {
  return page.evaluate((phone) => {
    const visible = (element: Element) => {
      const box = element.getBoundingClientRect()
      const style = getComputedStyle(element)
      return box.width > 0 && box.height > 0 && style.visibility !== 'hidden' && !element.closest('[aria-hidden="true"], .sr-only')
    }
    const name = (element: Element) => (element.getAttribute('aria-label') ?? element.textContent ?? '').trim().replace(/\s+/g, ' ').slice(0, 32)
    const smallTargets = phone
      ? [...document.querySelectorAll('a[href], button, [role="radio"], [role="menuitem"], [role="tab"], [role="option"], input:not([type="hidden"]), select, textarea')]
          .filter((element) => visible(element) && !element.closest('.sr-only'))
          .filter((element) => {
            const box = element.getBoundingClientRect()
            // A stretched link's target is its whole row or card; another control may reach past its box with an
            // absolutely placed ::after, such as a switch's hit area.
            const row = element.classList.contains('stretched-link') ? element.closest('tr, li, article') : null
            const after = getComputedStyle(element, '::after')
            const reach = after.position === 'absolute' ? Math.max(0, -parseFloat(after.top) || 0) + Math.max(0, -parseFloat(after.bottom) || 0) : 0
            const height = row ? row.getBoundingClientRect().height : box.height + reach
            return height < 44 && !(element instanceof HTMLInputElement && (element.type === 'checkbox' || element.type === 'radio'))
          })
          .map((element) => `${element.tagName.toLowerCase()} "${name(element)}" ${Math.round(element.getBoundingClientRect().width)}x${Math.round(element.getBoundingClientRect().height)}`)
      : []
    const clipped = [...document.querySelectorAll<HTMLElement>('body *')]
      .filter((element) => visible(element) && element.children.length === 0 && element.scrollWidth > element.clientWidth + 1)
      .filter((element) => {
        const style = getComputedStyle(element)
        return (style.overflow === 'hidden' || style.overflowX === 'hidden' || style.textOverflow === 'ellipsis') && !element.title
      })
      .map((element) => `"${name(element)}" ${element.scrollWidth}>${element.clientWidth}`)
    return { overflow: document.documentElement.scrollWidth - window.innerWidth, smallTargets, clipped }
  }, width < 768)
}

async function shoot(page: Page, file: string, viewportOnly: boolean) {
  const viewport = page.viewportSize()!
  if (viewportOnly) {
    await page.screenshot({ path: file })
    return
  }
  const height = await page.evaluate(() => document.documentElement.scrollHeight)
  await page.setViewportSize({ width: viewport.width, height: Math.max(viewport.height, height) })
  await page.waitForTimeout(400)
  const fits = await page.evaluate(() => document.documentElement.scrollHeight <= window.innerHeight)
  if (!fits) {
    // A page sized by the viewport, such as the settings editor, grows with it and never fits: it is shot whole at
    // its own viewport, where a fixed bar stays where the screen ended.
    await page.setViewportSize(viewport)
    await page.waitForTimeout(400)
  }
  await page.screenshot({ path: file, fullPage: !fits })
  await page.setViewportSize(viewport)
}

async function signedInPage(browser: Browser, options: Options, width: number, theme: Theme, session: Session) {
  const context = await browser.newContext({
    baseURL: options.url,
    viewport: { width, height: HEIGHTS[width] ?? 900 },
    locale: 'zh-TW',
    timezoneId: 'Asia/Taipei',
    colorScheme: theme,
    reducedMotion: 'reduce',
  })
  await context.addInitScript(([chosen]) => {
    localStorage.setItem('stock-agent.theme', chosen!)
    localStorage.setItem('stock-agent.locale', 'zh-TW')
  }, [theme])
  const account = session === 'admin' ? { identifier: options.user, password: options.password } : session === 'member' ? { identifier: options.member!, password: options.memberPassword! } : null
  if (account) {
    const answer = await context.request.post('/v1/auth/sign-in', { headers: { 'X-Requested-With': 'stock-agent' }, data: account })
    if (!answer.ok()) throw new Error(`sign-in of ${account.identifier} answered ${answer.status()}`)
  }
  const page = await context.newPage()
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error' && !/status of (401|403|404)/.test(message.text())) errors.push(message.text())
  })
  return { context, page, errors }
}

/** A fresh site has only the first-time setup to show; any other site, the latest run for the run detail. */
async function siteState(browser: Browser, options: Options): Promise<{ needsSetup: boolean; runId: string | null }> {
  const context = await browser.newContext({ baseURL: options.url })
  const status = (await (await context.request.get('/v1/auth/status')).json()) as { needs_first_administrator: boolean }
  if (status.needs_first_administrator) {
    await context.close()
    return { needsSetup: true, runId: null }
  }
  await context.request.post('/v1/auth/sign-in', { headers: { 'X-Requested-With': 'stock-agent' }, data: { identifier: options.user, password: options.password } })
  const runs = (await (await context.request.get('/v1/runs?limit=1')).json()) as { run_id: string }[]
  await context.close()
  return { needsSetup: false, runId: Array.isArray(runs) && runs[0] ? runs[0].run_id : null }
}

async function main() {
  const options = parseOptions(process.argv.slice(2))
  mkdirSync(options.out, { recursive: true })
  const browser = await chromium.launch()
  const findings: Finding[] = []
  try {
    const site = await siteState(browser, options)
    const all = shots(site.runId, site.needsSetup).filter((shot) => (!options.only || options.only.has(shot.name)) && (shot.session !== 'member' || options.member))
    for (const width of options.widths) {
      for (const theme of options.themes) {
        for (const session of ['signedOut', 'admin', 'member'] as const) {
          const mine = all.filter((shot) => shot.session === session && (!shot.phoneOnly || width < 768))
          if (mine.length === 0) continue
          const { context, page, errors } = await signedInPage(browser, options, width, theme, session)
          for (const shot of mine) {
            errors.length = 0
            await page.goto(shot.path)
            await settle(page)
            await shot.prepare?.(page)
            if (shot.prepare) await page.waitForTimeout(400)
            const name = `${shot.name}-${width}-${theme}`
            const found = await audit(page, width)
            await shoot(page, path.join(options.out, `${name}.png`), shot.viewportOnly ?? false)
            findings.push({ shot: name, ...found, errors: [...errors] })
            const notes = [found.overflow > 0 && `overflow ${found.overflow}px`, found.smallTargets.length && `${found.smallTargets.length} small`, found.clipped.length && `${found.clipped.length} clipped`, errors.length && `${errors.length} errors`].filter(Boolean)
            console.log(`${name}${notes.length ? `  ${notes.join(', ')}` : ''}`)
          }
          await context.close()
        }
      }
    }
  } finally {
    await browser.close()
  }
  writeFileSync(path.join(options.out, 'audit.json'), `${JSON.stringify(findings, null, 2)}\n`)
  const failing = findings.filter((finding) => finding.overflow > 0 || finding.smallTargets.length > 0 || finding.errors.length > 0)
  console.log(`${findings.length} shots; ${failing.length} with sideways scroll, a small phone control or a page error`)
  if (failing.length > 0) process.exitCode = 1
}

if (import.meta.main) await main()
