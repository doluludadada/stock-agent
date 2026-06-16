from datetime import datetime

from a_domain.model.market.article import Article
from a_domain.ports.market.news_provider import INewsProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.schemas.config import AppConfig
from c_infrastructure.feed.news.cnyes_news_provider import CnyesNewsProvider
from c_infrastructure.feed.news.yahoo_tw_news_provider import YahooTwNewsProvider


class NewsProvider(INewsProvider):
    def __init__(self, config: AppConfig, logger: ILoggingProvider):
        self._config = config
        self._logger = logger
        self._yahoo = YahooTwNewsProvider(logger)
        self._cnyes = CnyesNewsProvider(logger)

    async def fetch_news(self, stock_id: str, limit: int = 10) -> list[Article]:
        self._logger.debug(f"Fetching live news for {stock_id} from multiple sources...")

        articles: list[Article] = []

        try:
            articles.extend(await self._cnyes.fetch_news(stock_id, limit))
        except Exception as error:
            self._logger.warning(f"Cnyes news fetch failed for {stock_id}: {error}")

        if len(articles) < limit:
            try:
                articles.extend(await self._yahoo.fetch_news(stock_id, limit - len(articles)))
            except Exception as error:
                self._logger.warning(f"Yahoo news fetch failed for {stock_id}: {error}")

        seen_keys: set[str] = set()
        unique_articles: list[Article] = []

        for article in articles:
            key = article.url or article.title
            if key in seen_keys:
                continue

            seen_keys.add(key)
            unique_articles.append(article)

            if len(unique_articles) >= limit:
                break

        return unique_articles

    def save_as_md_file(self, stock_id: str, articles: list[Article]) -> None:
        """Saves a readable Markdown file so you can inspect exactly what the AI will read."""
        if not articles:
            return

        archive_dir_name = self._config.folder.news_archive_dir
        archive_dir = self._config.project_root / archive_dir_name / datetime.now().strftime("%Y-%m-%d")
        archive_dir.mkdir(parents=True, exist_ok=True)

        file_name = f"{stock_id}_{datetime.now().strftime('%H%M%S')}.md"
        file_path = archive_dir / file_name

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(f"# Market News: {stock_id}\n")
                f.write(f"**Generated at:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"**Total Articles:** {len(articles)}\n\n")
                f.write("---\n\n")

                for i, article in enumerate(articles, 1):
                    pub_time = article.published_at.strftime("%Y-%m-%d %H:%M")
                    f.write(f"## [{i}] {article.title}\n")
                    f.write(f"- **Source:** {article.source.value}\n")
                    f.write(f"- **Published:** {pub_time}\n")
                    f.write(f"- **URL:** [Link]({article.url})\n\n")
                    f.write(f"**Content Snippet:**\n> {article.content}\n\n")
                    f.write("---\n\n")

            self._logger.trace(f"Saved news archive to {file_path}")
        except Exception as e:
            self._logger.warning(f"Failed to save news archive for {stock_id}: {e}")
