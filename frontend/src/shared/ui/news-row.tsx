import { ExternalLink } from 'lucide-react'
import { useTranslation } from '@/i18n'
import { outboundUrl } from '@/shared/lib/outbound-url'
import { Badge } from './badge'

interface NewsRowProps {
  /** The source's name in the reader's language. */
  source: string
  publishedAt: string
  /** The time as the row says it: a day alone for a source that dates by the day. */
  time: string
  title: string
  url: string | null
  text?: string | null
  note?: string | null
}

/**
 * One item a third party published, in a list: its source and time, its title as the link out, and the text the site
 * may show of it. The title and the text render as text, and the address is a link only when it is http or https.
 */
export function NewsRow({ source, publishedAt, time, title, url, text, note }: NewsRowProps) {
  const { t } = useTranslation()
  const href = outboundUrl(url)
  return (
    <li className="space-y-1.5 px-4 py-3 md:px-5">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <Badge variant="outline" className="font-normal text-muted-foreground">
          {source}
        </Badge>
        <time dateTime={publishedAt} className="tabular">
          {time}
        </time>
        {note && <span>{note}</span>}
      </p>
      {href ? (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer nofollow"
          className="inline-flex min-h-11 items-start gap-1.5 py-1 text-sm font-medium text-pretty break-words hover:text-brand hover:underline md:min-h-0 md:py-0"
        >
          <span className="min-w-0">{title}</span>
          <ExternalLink aria-hidden className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
          <span className="sr-only">{t('opensSource')}</span>
        </a>
      ) : (
        <p className="text-sm font-medium text-pretty break-words">{title}</p>
      )}
      {text && <p className="line-clamp-3 text-sm text-pretty break-words whitespace-pre-line text-muted-foreground">{text}</p>}
    </li>
  )
}
