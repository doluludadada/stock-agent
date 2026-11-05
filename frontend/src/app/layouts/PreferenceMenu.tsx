import { Check, Languages, Monitor, Moon, Sun } from 'lucide-react'
import { changeLocale, SUPPORTED_LOCALES, useLocale, useTranslation } from '@/i18n'
import { useTheme, type ThemePreference } from '@/shared/lib/theme'
import { Button } from '@/shared/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/shared/ui/dropdown-menu'
import { Segmented } from '@/shared/ui/segmented'

const THEMES: readonly ThemePreference[] = ['light', 'dark', 'system']
const THEME_ICON = { dark: Moon, light: Sun, system: Monitor } as const

/** The language and theme menus of the header. */
export function PreferenceMenu() {
  const { t } = useTranslation()
  const locale = useLocale()
  const { preference, resolved, setPreference } = useTheme()
  const ThemeIcon = resolved === 'dark' ? Moon : Sun

  return (
    <div className="flex items-center">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button type="button" variant="ghost" size="icon" aria-label={t('preferences.language')} className="text-muted-foreground hover:text-foreground">
            <Languages aria-hidden className="size-4.5" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-44">
          <DropdownMenuLabel>{t('preferences.language')}</DropdownMenuLabel>
          <DropdownMenuSeparator />
          {SUPPORTED_LOCALES.map((item) => (
            <DropdownMenuItem key={item} onSelect={() => void changeLocale(item)} lang={item}>
              <span className="flex-1">{t(`preferences.locale.${item}`)}</span>
              {locale === item && <Check aria-hidden className="size-4 text-primary" />}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button type="button" variant="ghost" size="icon" aria-label={t('preferences.theme')} className="text-muted-foreground hover:text-foreground">
            <ThemeIcon aria-hidden className="size-4.5" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-44">
          <DropdownMenuLabel>{t('preferences.theme')}</DropdownMenuLabel>
          <DropdownMenuSeparator />
          {THEMES.map((item) => {
            const Icon = THEME_ICON[item]
            return (
              <DropdownMenuItem key={item} onSelect={() => setPreference(item)}>
                <Icon aria-hidden className="size-4" />
                <span className="flex-1">{t(`preferences.themes.${item}`)}</span>
                {preference === item && <Check aria-hidden className="size-4 text-primary" />}
              </DropdownMenuItem>
            )
          })}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

/** The same two choices as segmented controls, for the phone's "more" sheet. */
export function PreferenceControls() {
  const { t } = useTranslation()
  const locale = useLocale()
  const { preference, setPreference } = useTheme()
  return (
    <div className="grid gap-3">
      <Segmented
        value={locale}
        onChange={(next) => void changeLocale(next)}
        label={t('preferences.language')}
        options={SUPPORTED_LOCALES.map((item) => ({ value: item, label: t(`preferences.locale.${item}`) }))}
      />
      <Segmented value={preference} onChange={setPreference} label={t('preferences.theme')} options={THEMES.map((item) => ({ value: item, label: t(`preferences.themes.${item}`) }))} />
    </div>
  )
}
