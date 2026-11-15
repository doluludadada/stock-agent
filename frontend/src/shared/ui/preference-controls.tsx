import { Fragment } from 'react'
import { changeLocale, SUPPORTED_LOCALES, useLocale, useTranslation } from '@/i18n'
import { THEME_PREFERENCES, useTheme } from '@/shared/lib/theme'
import { Segmented } from '@/shared/ui/segmented'

/**
 * The language and the theme as segmented controls, which this browser keeps. Stacked, each names itself to a screen
 * reader alone; `labelled` shows each one's name above it, at the full width of its column.
 */
export function PreferenceControls({ labelled = false }: { labelled?: boolean }) {
  const { t } = useTranslation()
  const locale = useLocale()
  const { preference, setPreference } = useTheme()
  const width = labelled ? 'md:w-full' : undefined
  const controls = [
    {
      label: t('preferences.language'),
      control: (
        <Segmented
          value={locale}
          onChange={(next) => void changeLocale(next)}
          label={t('preferences.language')}
          options={SUPPORTED_LOCALES.map((item) => ({ value: item, label: t(`preferences.locale.${item}`) }))}
          className={width}
        />
      ),
    },
    {
      label: t('preferences.theme'),
      control: (
        <Segmented
          value={preference}
          onChange={setPreference}
          label={t('preferences.theme')}
          options={THEME_PREFERENCES.map((item) => ({ value: item, label: t(`preferences.themes.${item}`) }))}
          className={width}
        />
      ),
    },
  ]
  return (
    <div className={labelled ? 'grid gap-4 @md:grid-cols-2' : 'grid gap-3'}>
      {controls.map(({ label, control }) =>
        labelled ? (
          <div key={label} className="grid gap-1.5">
            <p className="text-sm leading-none font-medium">{label}</p>
            {control}
          </div>
        ) : (
          <Fragment key={label}>{control}</Fragment>
        ),
      )}
    </div>
  )
}
