import i18next from 'i18next'
import { initReactI18next, useTranslation } from 'react-i18next'
import { DEFAULT_LOCALE, initialLocale, isLocale, persistLocale, type Locale } from './language'
import { NAMESPACES, resources } from './resources'

export { useTranslation }
export { SUPPORTED_LOCALES, type Locale } from './language'

let initialized = false

/** Called once by the app provider; importing this module has no side effects. */
export function initI18n(locale: Locale = initialLocale()) {
  if (initialized) return i18next
  initialized = true
  void i18next.use(initReactI18next).init({
    resources,
    lng: locale,
    fallbackLng: DEFAULT_LOCALE,
    ns: NAMESPACES,
    defaultNS: 'common',
    initAsync: false,
    interpolation: { escapeValue: false },
    returnNull: false,
  })
  document.documentElement.lang = locale
  return i18next
}

export async function changeLocale(locale: Locale): Promise<void> {
  await i18next.changeLanguage(locale)
  persistLocale(locale)
}

/** The active locale from React, re-rendering when the language changes. */
export function useLocale(): Locale {
  const { i18n } = useTranslation()
  return isLocale(i18n.language) ? i18n.language : DEFAULT_LOCALE
}
