import { Search } from 'lucide-react'
import { useEffect } from 'react'
import { useNavigate } from 'react-router'
import { useTranslation } from '@/i18n'
import { paths } from '@/shared/config/paths'
import { cn } from '@/shared/lib/utils'
import { CommandDialog, CommandGroup, CommandItem, CommandSeparator } from '@/shared/ui/command'
import { StockSearchCommand } from '@/shared/ui/stock-picker'
import type { NavSection } from './navigation'

/** The header's search field; it opens the palette, where typing searches the listing. */
export function SearchField({ onOpen, className }: { onOpen: () => void; className?: string }) {
  const { t } = useTranslation()
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={t('search.open')}
      className={cn(
        'flex h-9 w-full max-w-md items-center gap-2.5 rounded-lg border bg-card px-3 text-sm text-muted-foreground shadow-card transition-colors outline-none hover:border-line-strong hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring',
        className,
      )}
    >
      <Search aria-hidden className="size-4 shrink-0" />
      <span className="flex-1 truncate text-left">{t('search.placeholder')}</span>
      <kbd aria-hidden className="rounded border bg-muted px-1.5 font-mono text-[0.625rem]">
        ⌘K
      </kbd>
    </button>
  )
}

/** Searches the backend's stock listing as the user types; nothing is fetched until the palette opens. */
export function SearchPalette({ open, onOpenChange, sections }: { open: boolean; onOpenChange: (open: boolean) => void; sections: readonly NavSection[] }) {
  const { t } = useTranslation()
  const navigate = useNavigate()

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        onOpenChange(!open)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onOpenChange])

  const go = (to: string) => {
    onOpenChange(false)
    navigate(to)
  }

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange} title={t('search.title')} description={t('search.description')}>
      <StockSearchCommand onSelect={(stockId) => go(paths.stock(stockId))} className="max-h-[min(60vh,26rem)]">
        <CommandSeparator />
        <CommandGroup heading={t('search.pages')}>
          {sections.flatMap((section) =>
            section.items.map((item) => (
              <CommandItem key={item.key} value={`page:${item.key}`} onSelect={() => go(item.to)}>
                <item.icon aria-hidden className="size-4 text-muted-foreground" />
                {t(`nav.${item.key}`)}
              </CommandItem>
            )),
          )}
        </CommandGroup>
      </StockSearchCommand>
    </CommandDialog>
  )
}
