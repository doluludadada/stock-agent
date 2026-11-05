import { Search } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { useLocale, useTranslation } from '@/i18n'
import { formatDate, formatPrice } from '@/shared/lib/format'
import { cn } from '@/shared/lib/utils'
import { Button } from './button'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from './command'
import { Popover, PopoverContent, PopoverTrigger } from './popover'
import { useStockSearch } from '@/shared/api'

/**
 * The listing search inside a Command, mounted only while its dialog or popover is open. Matches arrive after the
 * typing, so the first match is selected when it arrives: Enter opens it, not whatever was selected before.
 */
export function StockSearchCommand({ onSelect, children, className }: { onSelect: (stockId: string) => void; children?: ReactNode; className?: string }) {
  const { t } = useTranslation()
  const locale = useLocale()
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState('')
  const [selectedFor, setSelectedFor] = useState<string | undefined>()
  const search = useStockSearch(query)
  const first = search.results[0]?.stockId
  if (first !== selectedFor) {
    setSelectedFor(first)
    if (first) setSelected(first)
  }

  return (
    <Command shouldFilter={false} value={selected} onValueChange={setSelected}>
      <CommandInput placeholder={t('search.placeholder')} aria-label={t('search.open')} value={query} onValueChange={setQuery} />
      <CommandList className={cn('max-h-72', className)}>
        {search.status === 'idle' && <p className="px-3 py-3 text-sm text-muted-foreground">{t('search.hint')}</p>}
        {search.status === 'loading' && <p className="px-3 py-3 text-sm text-muted-foreground">{t('search.loading')}</p>}
        {search.status === 'error' && <p className="px-3 py-3 text-sm text-destructive">{t('search.failed')}</p>}
        {search.status === 'ready' && <CommandEmpty>{t('search.empty')}</CommandEmpty>}
        {search.results.length > 0 && (
          <CommandGroup heading={t('search.stocks')}>
            {search.results.map((stock) => (
              <CommandItem key={stock.stockId} value={stock.stockId} onSelect={() => onSelect(stock.stockId)}>
                <span className="w-14 font-mono text-xs text-muted-foreground">{stock.stockId}</span>
                <span className="flex-1 truncate">{stock.name}</span>
                {stock.close !== null && (
                  <span className="tabular text-xs" title={stock.session ? t('search.closeOn', { date: formatDate(locale, stock.session) }) : undefined}>
                    {formatPrice(locale, stock.close)}
                  </span>
                )}
              </CommandItem>
            ))}
          </CommandGroup>
        )}
        {children}
      </CommandList>
    </Command>
  )
}

/** A button that opens a listing search and hands back the chosen stock id. */
export function StockPicker({ label, onSelect }: { label: string; onSelect: (stockId: string) => void }) {
  const [open, setOpen] = useState(false)
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button type="button" variant="outline" size="sm">
          <Search aria-hidden />
          {label}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[min(20rem,calc(100vw-2rem))] gap-0 p-0">
        <StockSearchCommand
          onSelect={(stockId) => {
            setOpen(false)
            onSelect(stockId)
          }}
        />
      </PopoverContent>
    </Popover>
  )
}
