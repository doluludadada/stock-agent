import i18next from 'i18next'
import enAdmin from './locales/en/admin'
import zhAdmin from './locales/zh-TW/admin'

/**
 * The settings form's words: a label and a help for every setting, in both locales. Only an administrator's settings
 * page reads them, so they stay out of `resources`, which every page downloads, and load with that page's code.
 */
export const adminResources = { en: { admin: enAdmin }, 'zh-TW': { admin: zhAdmin } } as const

/** Adds the `admin` namespace to the running i18n, once. The settings page calls it before it reads a word. */
export function ensureAdminResources() {
  if (i18next.hasResourceBundle('en', 'admin')) return
  for (const [locale, bundle] of Object.entries(adminResources)) i18next.addResourceBundle(locale, 'admin', bundle.admin)
}
