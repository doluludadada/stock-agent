import { Activity, Calculator, Layers, Search, Sparkles, Star } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { useTranslation } from '@/i18n'
import { Button } from '@/shared/ui/button'
import { paths } from '@/shared/config/paths'
import { CommandDialog, CommandGroup, CommandItem, CommandSeparator } from '@/shared/ui/command'
import { StockSearchCommand } from '@/shared/ui/stock-picker'

const SHORTCUTS = [
  { key: 'strategies', to: paths.strategies, icon: Layers },
  { key: 'builder', to: paths.newStrategy, icon: Sparkles },
  { key: 'runs', to: paths.runs, icon: Activity },
  { key: 'valuation', to: paths.valuation, icon: Calculator },
  { key: 'watchlist', to: paths.watchlist, icon: Star },
] as const

/** Searches the backend's stock listing as the user types; nothing is fetched until the dialog opens. */
export function StockSearch() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setOpen((value) => !value)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const go = (to: string) => {
    setOpen(false)
    navigate(to)
  }

  return (
    <>
      <Button
        type="button"
        variant="outline"
        onClick={() => setOpen(true)}
        className="w-8 justify-center gap-2 px-0 text-muted-foreground sm:w-64 sm:justify-start sm:px-2.5 lg:w-80"
        aria-label={t('search.open')}
      >
        <Search aria-hidden className="size-4" />
        <span className="hidden flex-1 truncate text-left font-normal sm:inline">{t('search.placeholder')}</span>
        <kbd className="hidden rounded border bg-muted px-1.5 font-mono text-[0.625rem] sm:inline">⌘K</kbd>
      </Button>
      <CommandDialog open={open} onOpenChange={setOpen} title={t('search.title')} description={t('search.description')}>
        <StockSearchCommand onSelect={(stockId) => go(paths.stock(stockId))} className="max-h-[min(60vh,26rem)]">
          <CommandSeparator />
          <CommandGroup heading={t('search.pages')}>
            {SHORTCUTS.map((item) => (
              <CommandItem key={item.key} value={`page:${item.key}`} onSelect={() => go(item.to)}>
                <item.icon aria-hidden className="size-4 text-muted-foreground" />
                {t(`nav.${item.key}`)}
              </CommandItem>
            ))}
          </CommandGroup>
        </StockSearchCommand>
      </CommandDialog>
    </>
  )
}
