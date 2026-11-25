import type { SettingsProblem } from '@/shared/api'

type Wording = (key: string, options: Record<string, unknown>) => string

/**
 * What a problem says, in the reader's language: `admin:refusal.<code>` with the server's params for a code this app
 * words, such as pydantic's less_than_equal, else that the server refused the value.
 */
export function problemMessage(problem: SettingsProblem, t: Wording): string {
  const refused = t('common:errors.invalid', {})
  return problem.code ? t(`refusal.${problem.code}`, { ...problem.params, defaultValue: refused }) : refused
}
