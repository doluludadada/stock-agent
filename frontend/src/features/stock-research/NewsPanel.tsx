import { ExternalLink, Newspaper } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from '@/i18n'
import { useAllows } from '@/shared/api'
import { useFormat } from '@/shared/lib/format'
import { Badge } from '@/shared/ui/badge'
import { ErrorState } from '@/shared/ui/error-state'
import { Panel } from '@/shared/ui/panel'
import { ShowMore } from '@/shared/ui/show-more'
import { Skeleton } from '@/shared/ui/skeleton'
import { StateBlock } from '@/shared/ui/state-block'
import { useStockNews } from './api'
import { NEWS_SOURCES, newsText, outboundUrl, type NewsItem } from './model'

/** The first items are enough to see what is being said; the rest open on request. */
const ITEMS_SHOWN = 8

/**
 * What is said about the stock, newest first: the company's own announcements and the exchange's news from the open
 * data, and where the site may read them the news sites' articles and the board's posts, by title with a link out.
 * Every title and text is a third party's and renders as text; an address is a link only when it is http or https.
 */
export function NewsPanel({ stockId }: { stockId: string }) {
  const { t } = useTranslation('research')
  const news = useStockNews(stockId)
  const articles = useAllows('news_articles')
  const [expanded, setExpanded] = useState(false)
  const items = news.data?.items ?? []
  return (
    <Panel
      title={t('news.title')}
      flush
      footer={
        items.length > ITEMS_SHOWN && (
          <ShowMore
            expanded={expanded}
            onToggle={() => setExpanded(!expanded)}
            controls="stock-news"
            moreLabel={t('news.showAll', { count: items.length })}
            lessLabel={t('news.showLess')}
          />
        )
      }
    >
      {news.isPending && <Skeleton className="m-4 h-56 rounded-lg" />}
      {news.isError && <ErrorState error={news.error} title={t('news.failed')} onRetry={() => void news.refetch()} />}
      {news.data && items.length === 0 && (
        <StateBlock icon={Newspaper} title={t('news.none.title')} description={t(articles ? 'news.none.articles' : 'news.none.openData')} />
      )}
      {items.length > 0 && (
        <ul id="stock-news" className="divide-y">
          {(expanded ? items : items.slice(0, ITEMS_SHOWN)).map((item, index) => (
            <NewsRow key={`${item.source}-${item.published_at}-${index}`} item={item} />
          ))}
        </ul>
      )}
    </Panel>
  )
}

function NewsRow({ item }: { item: NewsItem }) {
  const { t } = useTranslation('research')
  const format = useFormat()
  const url = outboundUrl(item.url)
  const text = newsText(item)
  const time = NEWS_SOURCES[item.source].dayOnly ? format.date(item.published_at) : format.monthDayTime(item.published_at)
  return (
    <li className="space-y-1.5 px-4 py-3 md:px-5">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <Badge variant="outline" className="font-normal text-muted-foreground">
          {t(`news.source.${item.source}`)}
        </Badge>
        <time dateTime={item.published_at} className="tabular">
          {time}
        </time>
        {item.clause && <span>{item.clause}</span>}
      </p>
      {url ? (
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer nofollow"
          className="inline-flex min-h-11 items-start gap-1.5 py-1 text-sm font-medium text-pretty break-words hover:text-brand hover:underline md:min-h-0 md:py-0"
        >
          <span className="min-w-0">{item.title}</span>
          <ExternalLink aria-hidden className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
          <span className="sr-only">{t('news.opens')}</span>
        </a>
      ) : (
        <p className="text-sm font-medium text-pretty break-words">{item.title}</p>
      )}
      {text && <p className="line-clamp-3 text-sm text-pretty break-words whitespace-pre-line text-muted-foreground">{text}</p>}
    </li>
  )
}
