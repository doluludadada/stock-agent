/**
 * First-load measurement of a production build, repeatable on one machine.
 *
 *   bun tools/measure-load.ts <dist-dir> [--path /] [--api http://127.0.0.1:8800] [--runs 5] [--cpu 4]
 *
 * It serves <dist-dir> gzip-compressed with an SPA fallback, proxies /v1 to --api when given (otherwise /v1
 * answers 503), opens --path in headless Chromium with the CPU slowed --cpu times, and prints the median of
 * --runs cold loads: requests, bytes on the wire, DOMContentLoaded, load, largest contentful paint and the
 * main-thread long tasks until the network is idle. A load with an uncaught error, a console error other than a failed
 * resource, or no rendered main landmark prints the error and makes the exit code 1. Numbers compare builds on the same machine only.
 */
import { existsSync, readFileSync, statSync } from 'node:fs'
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http'
import type { AddressInfo } from 'node:net'
import path from 'node:path'
import { gzipSync } from 'node:zlib'
import { chromium } from '@playwright/test'

interface Options {
  dist: string
  route: string
  api: string | null
  runs: number
  cpu: number
}

interface Sample {
  requests: number
  apiRequests: number
  scriptBytes: number
  totalBytes: number
  domContentLoaded: number
  load: number
  lcp: number
  longTaskCount: number
  longTaskMs: number
  pageErrors: number
}

function parseOptions(argv: string[]): Options {
  const [dist, ...rest] = argv
  if (!dist || !existsSync(dist)) throw new Error('usage: bun tools/measure-load.ts <dist-dir> [--path /] [--api URL] [--runs 5] [--cpu 4]')
  const flag = (name: string) => {
    const index = rest.indexOf(`--${name}`)
    return index >= 0 ? rest[index + 1] ?? null : null
  }
  return {
    dist: path.resolve(dist),
    route: flag('path') ?? '/',
    api: flag('api'),
    runs: Number(flag('runs') ?? 5),
    cpu: Number(flag('cpu') ?? 4),
  }
}

const CONTENT_TYPES: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.woff2': 'font/woff2',
  '.json': 'application/json',
}

async function answer(options: Options, request: IncomingMessage, response: ServerResponse) {
  const url = new URL(request.url ?? '/', 'http://localhost')
  if (url.pathname.startsWith('/v1')) {
    if (!options.api) return response.writeHead(503).end('no api')
    const upstream = await fetch(new URL(url.pathname + url.search, options.api), {
      method: request.method,
      headers: { authorization: request.headers.authorization ?? '' },
    })
    response.writeHead(upstream.status, { 'content-type': upstream.headers.get('content-type') ?? 'application/json' })
    return response.end(Buffer.from(await upstream.arrayBuffer()))
  }
  const candidate = path.join(options.dist, url.pathname)
  const isFile = candidate.startsWith(options.dist) && existsSync(candidate) && statSync(candidate).isFile()
  const file = isFile ? candidate : path.join(options.dist, 'index.html')
  const body = readFileSync(file)
  const type = CONTENT_TYPES[path.extname(file)] ?? 'application/octet-stream'
  const compressible = !file.endsWith('.woff2')
  response.writeHead(200, { 'content-type': type, 'cache-control': 'no-store', ...(compressible ? { 'content-encoding': 'gzip' } : {}) })
  response.end(compressible ? gzipSync(body) : body)
}

async function serve(options: Options) {
  const server = createServer((request, response) => void answer(options, request, response))
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  return { port: (server.address() as AddressInfo).port, stop: () => server.close() }
}

async function measureOnce(baseUrl: string, options: Options): Promise<Sample> {
  const browser = await chromium.launch()
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-TW', timezoneId: 'Asia/Taipei' })
  const page = await context.newPage()
  const cdp = await context.newCDPSession(page)
  await cdp.send('Network.enable')
  await cdp.send('Network.setCacheDisabled', { cacheDisabled: true })
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: options.cpu })
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error' && !message.text().startsWith('Failed to load resource')) errors.push(message.text())
  })
  const types = new Map<string, string>()
  const urls = new Map<string, string>()
  let totalBytes = 0
  let scriptBytes = 0
  cdp.on('Network.responseReceived', (event) => {
    types.set(event.requestId, event.type)
    urls.set(event.requestId, event.response.url)
  })
  cdp.on('Network.loadingFinished', (event) => {
    totalBytes += event.encodedDataLength
    if (types.get(event.requestId) === 'Script') scriptBytes += event.encodedDataLength
  })
  await page.addInitScript(() => {
    const state = { lcp: 0, longTaskCount: 0, longTaskMs: 0 }
    Object.assign(window, { __measure: state })
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) state.lcp = entry.startTime
    }).observe({ type: 'largest-contentful-paint', buffered: true })
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        state.longTaskCount += 1
        state.longTaskMs += entry.duration
      }
    }).observe({ type: 'longtask', buffered: true })
  })
  await page.goto(new URL(options.route, baseUrl).toString(), { waitUntil: 'networkidle' })
  await page.waitForTimeout(500)
  if ((await page.locator('main').count()) === 0) errors.push('the app rendered no main landmark')
  for (const error of errors) console.error(`page error: ${error}`)
  const timing = await page.evaluate(() => {
    const [navigation] = performance.getEntriesByType('navigation') as PerformanceNavigationTiming[]
    const measure = (window as unknown as { __measure: { lcp: number; longTaskCount: number; longTaskMs: number } }).__measure
    return { domContentLoaded: navigation?.domContentLoadedEventEnd ?? 0, load: navigation?.loadEventEnd ?? 0, ...measure }
  })
  const apiRequests = [...urls.values()].filter((url) => new URL(url).pathname.startsWith('/v1')).length
  await browser.close()
  return { requests: urls.size, apiRequests, scriptBytes, totalBytes, ...timing, pageErrors: errors.length }
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b)
  return sorted[Math.floor(sorted.length / 2)] ?? 0
}

const options = parseOptions(process.argv.slice(2))
const server = await serve(options)
const samples: Sample[] = []
for (let run = 0; run < options.runs; run += 1) samples.push(await measureOnce(`http://127.0.0.1:${server.port}`, options))
server.stop()

const keys = Object.keys(samples[0]!) as (keyof Sample)[]
const result = Object.fromEntries(keys.map((key) => [key, Math.round(median(samples.map((sample) => sample[key])))]))
console.log(JSON.stringify({ dist: options.dist, route: options.route, cpuSlowdown: options.cpu, runs: options.runs, median: result }, null, 2))
if (samples.some((sample) => sample.pageErrors > 0)) process.exitCode = 1
