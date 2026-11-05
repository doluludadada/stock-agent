/**
 * Enforces the frontend ownership rules in docs/frontend-guide.md:
 *   app -> features -> shared; features never import each other; outside code uses a feature only
 *   through its index.ts; shared and i18n never import business code. It also rejects raw colors in
 *   app/feature code, `href="#"` placeholders and empty click handlers.
 * Run: bun tools/check-boundaries.ts [srcDir]
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'

export interface Violation {
  file: string
  rule: string
  detail: string
}

const SOURCE = /\.(ts|tsx)$/
const IMPORT = /(?:import|export)\s[^'"]*?from\s*['"]([^'"]+)['"]|import\(\s*['"]([^'"]+)['"]\s*\)/g

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name)
    return statSync(full).isDirectory() ? walk(full) : SOURCE.test(name) ? [full] : []
  })
}

type Area = { kind: 'app' | 'shared' | 'i18n' | 'styles' | 'root' } | { kind: 'feature'; name: string }

function areaOf(relative: string): Area {
  const [top, second] = relative.split('/')
  if (top === 'features' && second) return { kind: 'feature', name: second }
  if (top === 'app' || top === 'shared' || top === 'i18n' || top === 'styles') return { kind: top }
  return { kind: 'root' }
}

function resolveImport(srcDir: string, file: string, specifier: string): string | null {
  if (specifier.startsWith('@/')) return specifier.slice(2)
  if (specifier.startsWith('.')) return path.relative(srcDir, path.resolve(path.dirname(file), specifier)).split(path.sep).join('/')
  return null
}

function isFeatureEntry(target: string): boolean {
  const parts = target.replace(/\.(ts|tsx)$/, '').split('/')
  return parts.length === 2 || (parts.length === 3 && parts[2] === 'index')
}

function checkImport(from: Area, target: string): string | null {
  const to = areaOf(target)
  if (from.kind === 'feature') {
    if (to.kind === 'feature' && to.name !== from.name) return `cross-feature import of features/${to.name}`
    if (to.kind === 'app') return 'feature imports app'
    return null
  }
  if ((from.kind === 'shared' || from.kind === 'i18n' || from.kind === 'styles') && (to.kind === 'feature' || to.kind === 'app')) {
    return `${from.kind} imports ${to.kind === 'feature' ? `features/${to.name}` : 'app'}`
  }
  if (to.kind === 'feature' && !isFeatureEntry(target)) return `bypasses the public index of features/${to.name}`
  return null
}

const RAW_COLOR = /(['"`][^'"`]*?)(#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|oklch|oklab)\()/
const PLACEHOLDER_HREF = /href=["']#["']/
const EMPTY_HANDLER = /on[A-Z]\w*=\{\s*\(\s*\)\s*=>\s*(?:\{\s*\}|undefined|null)\s*\}/

export function findViolations(srcDir: string): Violation[] {
  const violations: Violation[] = []
  for (const file of walk(srcDir)) {
    const relative = path.relative(srcDir, file).split(path.sep).join('/')
    if (/\.test\.tsx?$/.test(relative)) continue
    const from = areaOf(relative)
    const text = readFileSync(file, 'utf8')
    for (const match of text.matchAll(IMPORT)) {
      const specifier = match[1] ?? match[2]
      if (!specifier) continue
      const target = resolveImport(srcDir, file, specifier)
      const problem = target ? checkImport(from, target) : null
      if (problem) violations.push({ file: relative, rule: 'boundary', detail: `${problem} (${specifier})` })
    }
    if (from.kind === 'feature' || from.kind === 'app') {
      const color = text.match(RAW_COLOR)
      if (color) violations.push({ file: relative, rule: 'raw-color', detail: `use a token from styles/tokens.css instead of ${color[2]}` })
    }
    if (PLACEHOLDER_HREF.test(text)) violations.push({ file: relative, rule: 'placeholder-link', detail: 'href="#" is a fake link' })
    if (EMPTY_HANDLER.test(text)) violations.push({ file: relative, rule: 'empty-handler', detail: 'an event handler that does nothing' })
  }
  return violations
}

if (import.meta.main) {
  const srcDir = path.resolve(process.argv[2] ?? 'src')
  const violations = findViolations(srcDir)
  for (const violation of violations) console.error(`${violation.file}: [${violation.rule}] ${violation.detail}`)
  console.log(`boundaries: ${violations.length} violation(s)`)
  process.exit(violations.length === 0 ? 0 : 1)
}
