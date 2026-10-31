from datetime import datetime
from typing import override

from a_domain.model.market.article import Article
from a_domain.ports.market.news_provider import INewsProvider
from a_domain.ports.market.news_source import INewsSource
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.config.app_config import AppConfig


class NewsProvider(INewsProvider):
    """Asks each news site in turn until it has enough articles. A site that fails is skipped."""

    def __init__(self, sources: tuple[INewsSource, ...], config: AppConfig, logger: ILoggingProvider):
        self._sources = sources
        self._config = config
        self._logger = logger

    @override
    async def fetch_news(self, stock_id: str, limit: int = 10) -> list[Article]:
        self._logger.debug(f"Fetching live news for {stock_id} from {len(self._sources)} sources...")
        articles: list[Article] = []

        for source in self._sources:
            if len(articles) >= limit:
                break

            try:
                articles.extend(await source.fetch_news(stock_id, limit - len(articles)))
            except Exception as error:
                self._logger.warning(f"{type(source).__name__} news fetch failed for {stock_id}: {error}")

        unique_articles: dict[str, Article] = {}

        for article in articles:
            unique_articles.setdefault(article.url or article.title, article)

        return list(unique_articles.values())[:limit]

    @override
    def save_as_md_file(self, stock_id: str, articles: list[Article]) -> None:
        """Saves a readable Markdown file so you can inspect exactly what the AI will read."""
        if not articles:
            return

        now = datetime.now()
        archive_dir = self._config.project_root / self._config.folder.news_archive_dir / now.strftime("%Y-%m-%d")
        archive_dir.mkdir(parents=True, exist_ok=True)
        file_path = archive_dir / f"{stock_id}_{now.strftime('%H%M%S')}.md"

        try:
            with open(file_path, "w", encoding="utf-8") as file:
                file.write(f"# Market News: {stock_id}\n")
                file.write(f"**Generated at:** {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
                file.write(f"**Total Articles:** {len(articles)}\n\n")
                file.write("---\n\n")

                for index, article in enumerate(articles, 1):
                    file.write(f"## [{index}] {article.title}\n")
                    file.write(f"- **Source:** {article.source.value}\n")
                    file.write(f"- **Published:** {article.published_at.strftime('%Y-%m-%d %H:%M')}\n")
                    file.write(f"- **URL:** [Link]({article.url})\n\n")
                    file.write(f"**Content Snippet:**\n> {article.content}\n\n")
                    file.write("---\n\n")

            self._logger.trace(f"Saved news archive to {file_path}")
        except Exception as error:
            self._logger.warning(f"Failed to save news archive for {stock_id}: {error}")
