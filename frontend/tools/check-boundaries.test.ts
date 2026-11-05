import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { findViolations } from './check-boundaries'

function project(files: Record<string, string>): string {
  const root = mkdtempSync(path.join(tmpdir(), 'boundaries-'))
  for (const [name, content] of Object.entries(files)) {
    const full = path.join(root, name)
    mkdirSync(path.dirname(full), { recursive: true })
    writeFileSync(full, content)
  }
  return root
}

describe('feature boundaries', () => {
  it('the real source tree has no violations', () => {
    expect(findViolations(path.resolve(import.meta.dirname, '../src'))).toEqual([])
  })

  it('catches cross-feature imports through the alias and through relative paths', () => {
    const root = project({
      'features/screening/a.ts': "import { x } from '@/features/watchlist'\nimport { y } from '../watchlist/store'\n",
      'features/watchlist/index.ts': 'export const x = 1\n',
      'features/watchlist/store.ts': 'export const y = 1\n',
    })
    const rules = findViolations(root).map((violation) => violation.detail)
    expect(rules).toEqual([
      'cross-feature import of features/watchlist (@/features/watchlist)',
      'cross-feature import of features/watchlist (../watchlist/store)',
    ])
  })

  it('lets app compose features only through their public index', () => {
    const root = project({
      'app/routes.tsx': "import { A } from '@/features/screening'\nimport { B } from '@/features/screening/model'\n",
    })
    expect(findViolations(root).map((violation) => violation.detail)).toEqual([
      'bypasses the public index of features/screening (@/features/screening/model)',
    ])
  })

  it('keeps shared and i18n free of business code', () => {
    const root = project({
      'shared/ui/x.tsx': "import { A } from '@/features/screening'\n",
      'i18n/index.ts': "import { App } from '../app/App'\n",
    })
    expect(findViolations(root).map((violation) => violation.detail).sort()).toEqual([
      'i18n imports app (../app/App)',
      'shared imports features/screening (@/features/screening)',
    ])
  })

  it('rejects raw colors in features, fake links and empty handlers', () => {
    const root = project({
      'features/a/View.tsx': 'export const A = () => <a href="#" className="text-[#ff0000]" onClick={() => {}} />\n',
    })
    expect(findViolations(root).map((violation) => violation.rule).sort()).toEqual(['empty-handler', 'placeholder-link', 'raw-color'])
  })
})
