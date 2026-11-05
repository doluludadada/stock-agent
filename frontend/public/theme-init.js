// Applies the saved theme and language before first paint; the keys match shared/lib/theme.tsx and i18n/language.ts.
// It is a file, not an inline script, so the Content-Security-Policy can allow scripts from this origin only.
try {
  var theme = localStorage.getItem('stock-agent.theme') || 'system'
  var dark = theme === 'dark' || (theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.classList.toggle('dark', dark)
  var locale = localStorage.getItem('stock-agent.locale')
  if (locale === 'en' || locale === 'zh-TW') document.documentElement.lang = locale
} catch {}
