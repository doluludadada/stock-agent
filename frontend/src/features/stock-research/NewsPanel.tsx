import { Newspaper } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from '@/i18n'
import { useAllows } from '@/shared/api'
import { useFormat } from '@/shared/lib/format'
import { ErrorState } from '@/shared/ui/error-state'
import { NewsRow } from '@/shared/ui/news-row'
import { Panel } from '@/shared/ui/panel'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { ShowMore } from '@/shared/ui/show-more'
import { Skeleton } from '@/shared/ui/skeleton'
import { StateBlock } from '@/shared/ui/state-block'
import { useStockNews } from './api'
import { NEWS_SOURCES, newsText, type NewsItem } from './model'

/** The first items are enough to see what is being said; the rest open on request. */
const ITEMS_SHOWN = 8

/**
 * What is said about the stock, newest first: the company's own announcements and the exchange's news from the open
 * data, and where the site may read them the news sites' articles and the board's posts, by title with a link out.
 * Every title and text is a third party's and renders as text; an address is a link only when it is http or https.
 * The server answers a signed-in viewer only, so a visitor is told what signing in opens and nothing is asked.
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
      <RequireSignIn reason={t('news.signIn')}>
        {news.isPending && <Skeleton className="m-4 h-56 rounded-lg" />}
        {news.isError && <ErrorState error={news.error} title={t('news.failed')} onRetry={() => void news.refetch()} />}
        {news.data && items.length === 0 && (
          <StateBlock icon={Newspaper} title={t('news.none.title')} description={t(articles ? 'news.none.articles' : 'news.none.openData')} />
        )}
        {items.length > 0 && (
          <ul id="stock-news" className="divide-y">
            {(expanded ? items : items.slice(0, ITEMS_SHOWN)).map((item, index) => (
              <StockNewsRow key={`${item.source}-${item.published_at}-${index}`} item={item} />
            ))}
          </ul>
        )}
      </RequireSignIn>
    </Panel>
  )
}

function StockNewsRow({ item }: { item: NewsItem }) {
  const { t } = useTranslation('research')
  const format = useFormat()
  const time = NEWS_SOURCES[item.source].dayOnly ? format.date(item.published_at) : format.monthDayTime(item.published_at)
  return (
    <NewsRow source={t(`news.source.${item.source}`)} publishedAt={item.published_at} time={time} title={item.title} url={item.url} text={newsText(item)} note={item.clause} />
  )
}
